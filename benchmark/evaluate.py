"""
Evaluation engine for the polyphonic pitch detector.

Responsibilities
----------------
1. Run PitchDetector over every clip in a dataset at one or more window sizes.
2. Align detector output windows with reference annotation frames using
   mir_eval.multipitch.
3. Collect per-clip and per-dataset statistics and return them as a DataFrame.

Evaluation metric
-----------------
We use **multipitch accuracy** (mir_eval vocabulary: "Accuracy"):

    Accuracy = TP / (TP + FP + FN)

where TP/FP/FN are computed *per frame* in Hz space, with a ±0.5-semitone
tolerance window.  Because the user only cares about semitone-level accuracy we
also report "rounded-MIDI precision/recall/F1" by first rounding all reference
and estimated frequencies to the nearest MIDI integer before evaluation.

Speed metric
------------
For each (dataset, window_size) pair we report:
    real_time_factor = audio_duration / processing_time
A factor > 1.0 means faster than real-time.
"""

from __future__ import annotations

import time
import warnings
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import mir_eval
import librosa

from .pitch_detector import PitchDetector, note_to_frequency, NUM_OF_RESONATOR, FIRST_NOTE_NUMBER
from .datasets.base import BaseDataset, DatasetSample

if TYPE_CHECKING:
    pass


# ── tolerance used by mir_eval.multipitch ──────────────────────────────────────
# 0.5 semitones = quarter-tone; we want *exactly* MIDI-rounded accuracy, so
# we use a tolerance just under half a semitone so that a note is only
# accepted if it rounds to the correct MIDI integer.
MIDI_TOLERANCE_CENTS = 50.0  # ±50 cents  (mir_eval uses cents internally)


# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class ClipResult:
    """Evaluation results for a single audio clip at one window size."""

    clip_name:         str
    dataset_name:      str
    window_size:       int
    sample_rate:       float
    latency_ms:        float

    # mir_eval multipitch metrics (rounded-MIDI version)
    precision:         float
    recall:            float
    f1:                float
    accuracy:          float   # TP / (TP + FP + FN)

    # mir_eval raw multipitch metrics (Hz-space, 0.5-semitone tolerance)
    precision_hz:      float
    recall_hz:         float
    f1_hz:             float
    accuracy_hz:       float

    # Totals for manual aggregation
    n_ref_notes:       int     # total reference note-frame activations
    n_est_notes:       int     # total estimated note-frame activations
    n_tp:              int

    # Speed
    audio_duration_s:  float
    processing_time_s: float
    real_time_factor:  float

    # Number of evaluation frames
    n_frames:          int

    def to_dict(self) -> dict:
        return self.__dict__


@dataclass
class BenchmarkResult:
    """Aggregated results for one (dataset, window_size) combination."""

    dataset_name:    str
    window_size:     int
    latency_ms:      float
    sample_rate:     float
    n_clips:         int

    mean_precision:  float
    mean_recall:     float
    mean_f1:         float
    mean_accuracy:   float

    mean_precision_hz: float
    mean_recall_hz:    float
    mean_f1_hz:        float
    mean_accuracy_hz:  float

    mean_rtf:        float   # real-time factor (higher = faster)

    clip_results:    list[ClipResult] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "clip_results"}
        return d


# ─────────────────────────────────────────────────────────────────────────────
def _detector_output_to_multipitch(
    window_notes: list[list[int]],
    window_size:  int,
    sample_rate:  float,
) -> tuple[np.ndarray, list[np.ndarray]]:
    """
    Convert the detector's per-window MIDI-note lists into (times, freqs) arrays
    suitable for mir_eval.multipitch.evaluate().

    The timestamp for each window is placed at the *end* of the window
    (earliest time the detector could have produced output).
    """
    n = len(window_notes)
    times = np.array([(i + 1) * window_size / sample_rate for i in range(n)])
    freqs = [
        np.array([note_to_frequency(m) for m in notes], dtype=np.float64)
        for notes in window_notes
    ]
    return times, freqs


def _round_freqs_to_midi(
    freqs_list: list[np.ndarray],
) -> list[np.ndarray]:
    """
    Round all frequencies to the nearest MIDI note (in Hz).
    This collapses pitch-bend detail so that evaluation is purely semitone-level.
    """
    out = []
    for freqs in freqs_list:
        if len(freqs) == 0:
            out.append(np.array([], dtype=np.float64))
        else:
            midi_rounded = np.round(12.0 * np.log2(freqs / 440.0) + 69.0).astype(int)
            hz_rounded   = np.array([2.0 ** ((m - 69) / 12.0) * 440.0 for m in midi_rounded])
            # deduplicate (two strings may round to same note)
            out.append(np.unique(hz_rounded))
    return out


def _resample_ref_to_est_times(
    ref_times:  np.ndarray,
    ref_freqs:  list[np.ndarray],
    est_times:  np.ndarray,
) -> tuple[np.ndarray, list[np.ndarray], np.ndarray, list[np.ndarray]]:
    """
    Subsample reference annotation frames to the nearest detector output time,
    so that ref and est arrays are time-aligned for mir_eval.

    Returns (aligned_ref_times, aligned_ref_freqs, est_times, est_freqs_subset).
    We also trim est to the range covered by ref.
    """
    if len(ref_times) == 0 or len(est_times) == 0:
        return ref_times, ref_freqs, est_times, [np.array([]) for _ in est_times]

    # Use only est windows that fall within the reference annotation span
    valid = (est_times >= ref_times[0]) & (est_times <= ref_times[-1])
    est_times_v = est_times[valid]

    if len(est_times_v) == 0:
        empty = [np.array([], dtype=np.float64)]
        return est_times_v, empty, est_times_v, empty

    # For each est_time, find the closest ref_time
    idx = np.searchsorted(ref_times, est_times_v)
    idx = np.clip(idx, 0, len(ref_times) - 1)
    # Prefer the closer of idx-1 and idx
    for k in range(len(idx)):
        i = idx[k]
        if i > 0:
            if abs(ref_times[i - 1] - est_times_v[k]) < abs(ref_times[i] - est_times_v[k]):
                idx[k] = i - 1

    aligned_ref_times = ref_times[idx]
    aligned_ref_freqs = [ref_freqs[i] for i in idx]

    # est_freqs corresponding to valid windows
    valid_indices = np.where(valid)[0]
    return aligned_ref_times, aligned_ref_freqs, est_times_v, valid_indices


def evaluate_clip(
    sample:      DatasetSample,
    window_size: int,
    threshold:   float = 0.001,
) -> ClipResult:
    """
    Run the pitch detector on one audio clip and evaluate against ground truth.
    """
    sr = sample.sample_rate

    # Resample to 44100 Hz if needed (detector default; preserves algorithm fidelity)
    target_sr = 44100
    if sr != target_sr:
        audio = librosa.resample(sample.audio, orig_sr=sr, target_sr=target_sr)
        sr    = target_sr
    else:
        audio = sample.audio

    detector = PitchDetector(
        sample_rate = float(sr),
        window_size = window_size,
        threshold   = threshold,
    )

    # ---- run detector ----
    t0 = time.perf_counter()
    raw_windows = detector.process_audio(audio)
    proc_time   = time.perf_counter() - t0

    audio_duration = len(audio) / sr

    # ---- build est arrays ----
    est_times, est_freqs = _detector_output_to_multipitch(raw_windows, window_size, sr)

    # ---- align ref frames to est times ----
    ref_times = sample.ref_times
    ref_freqs = sample.ref_freqs

    aligned_ref_times, aligned_ref_freqs, est_times_v, valid_est_idx = \
        _resample_ref_to_est_times(ref_times, ref_freqs, est_times)

    if len(est_times_v) == 0:
        # No overlapping frames — return zeros
        return ClipResult(
            clip_name=sample.name, dataset_name="", window_size=window_size,
            sample_rate=sr, latency_ms=1000.0 * window_size / sr,
            precision=0, recall=0, f1=0, accuracy=0,
            precision_hz=0, recall_hz=0, f1_hz=0, accuracy_hz=0,
            n_ref_notes=0, n_est_notes=0, n_tp=0,
            audio_duration_s=audio_duration, processing_time_s=proc_time,
            real_time_factor=audio_duration / max(proc_time, 1e-9),
            n_frames=0,
        )

    est_freqs_v = [est_freqs[i] for i in valid_est_idx]

    # ---- rounded-MIDI evaluation ----
    ref_midi = _round_freqs_to_midi(aligned_ref_freqs)
    est_midi = _round_freqs_to_midi(est_freqs_v)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        scores_midi = mir_eval.multipitch.evaluate(
            aligned_ref_times, ref_midi,
            est_times_v,       est_midi,
        )

    # ---- raw Hz evaluation (0.5-semitone tolerance) ----
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        scores_hz = mir_eval.multipitch.evaluate(
            aligned_ref_times, aligned_ref_freqs,
            est_times_v,       est_freqs_v,
        )

    # mir_eval.multipitch does not return F-measure — compute it
    def _f1(p, r):
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    p_midi = float(scores_midi.get("Precision", 0))
    r_midi = float(scores_midi.get("Recall",    0))
    p_hz   = float(scores_hz.get("Precision",   0))
    r_hz   = float(scores_hz.get("Recall",      0))

    # ---- count TP / FP / FN for accuracy ----
    n_ref = sum(len(f) for f in aligned_ref_freqs)
    n_est = sum(len(f) for f in est_freqs_v)
    # mir_eval precision = TP/n_est, recall = TP/n_ref => TP = recall * n_ref
    tp_midi = round(r_midi * n_ref)

    return ClipResult(
        clip_name         = sample.name,
        dataset_name      = "",
        window_size       = window_size,
        sample_rate       = float(sr),
        latency_ms        = 1000.0 * window_size / sr,
        precision         = p_midi,
        recall            = r_midi,
        f1                = _f1(p_midi, r_midi),
        accuracy          = float(scores_midi.get("Accuracy",  0)),
        precision_hz      = p_hz,
        recall_hz         = r_hz,
        f1_hz             = _f1(p_hz, r_hz),
        accuracy_hz       = float(scores_hz.get("Accuracy",    0)),
        n_ref_notes       = n_ref,
        n_est_notes       = n_est,
        n_tp              = tp_midi,
        audio_duration_s  = audio_duration,
        processing_time_s = proc_time,
        real_time_factor  = audio_duration / max(proc_time, 1e-9),
        n_frames          = len(est_times_v),
    )


# ─────────────────────────────────────────────────────────────────────────────
def run_benchmark(
    datasets:     list[tuple[str, BaseDataset]],
    window_sizes: list[int] | None = None,
    threshold:    float            = 0.001,
    sample_rate:  float            = 44100.0,
    verbose:      bool             = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Run the full benchmark across all provided datasets and window sizes.

    Parameters
    ----------
    datasets
        List of (name, dataset_instance) pairs.
    window_sizes
        List of window sizes in samples to sweep. Default covers ~5 ms to 185 ms.
    threshold
        Energy threshold for note-on detection.
    sample_rate
        Detector sample rate (audio will be resampled to this if necessary).
    verbose
        Print progress to stdout.

    Returns
    -------
    clip_df : DataFrame
        One row per (clip, window_size).
    summary_df : DataFrame
        One row per (dataset, window_size) with mean metrics.
    """
    if window_sizes is None:
        window_sizes = [256, 512, 960, 1024, 2048, 4096, 8192]

    all_clip_results: list[ClipResult] = []

    for ds_name, dataset in datasets:
        if not dataset.is_available():
            if verbose:
                print(f"  [{ds_name}] NOT AVAILABLE — skipping")
            continue

        for ws in window_sizes:
            latency_ms = 1000.0 * ws / sample_rate
            if verbose:
                print(f"  [{ds_name}] window={ws} ({latency_ms:.1f} ms) ...", flush=True)

            for sample in dataset:
                try:
                    result = evaluate_clip(sample, ws, threshold)
                    result.dataset_name = ds_name
                    all_clip_results.append(result)
                except Exception as exc:
                    if verbose:
                        print(f"    ERROR on {sample.name}: {exc}")

            if verbose:
                ws_results = [r for r in all_clip_results
                              if r.dataset_name == ds_name and r.window_size == ws]
                if ws_results:
                    mean_acc = np.mean([r.accuracy for r in ws_results])
                    mean_f1  = np.mean([r.f1        for r in ws_results])
                    mean_rtf = np.mean([r.real_time_factor for r in ws_results])
                    print(f"    → {len(ws_results)} clips, "
                          f"acc={mean_acc:.3f}, f1={mean_f1:.3f}, RTF={mean_rtf:.1f}x")

    if not all_clip_results:
        empty = pd.DataFrame()
        return empty, empty

    clip_df = pd.DataFrame([r.to_dict() for r in all_clip_results])

    # Aggregate
    agg_rows = []
    for (ds_name, ws), grp in clip_df.groupby(["dataset_name", "window_size"]):
        mp   = grp["precision"].mean()
        mr   = grp["recall"].mean()
        mp_hz = grp["precision_hz"].mean()
        mr_hz = grp["recall_hz"].mean()

        def _f1(p, r):
            return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

        agg_rows.append({
            "dataset":          ds_name,
            "window_size":      ws,
            "latency_ms":       round(1000.0 * ws / sample_rate, 2),
            "n_clips":          len(grp),
            "mean_precision":   mp,
            "mean_recall":      mr,
            "mean_f1":          grp["f1"].mean(),
            "mean_accuracy":    grp["accuracy"].mean(),
            "mean_precision_hz": mp_hz,
            "mean_recall_hz":   mr_hz,
            "mean_f1_hz":       grp["f1_hz"].mean(),
            "mean_accuracy_hz": grp["accuracy_hz"].mean(),
            "mean_rtf":         grp["real_time_factor"].mean(),
        })
    summary_df = pd.DataFrame(agg_rows)

    return clip_df, summary_df


# ─────────────────────────────────────────────────────────────────────────────
def print_summary(summary_df: pd.DataFrame) -> None:
    """Pretty-print the summary table."""
    if summary_df.empty:
        print("No results to display.")
        return

    print("\n" + "=" * 90)
    print("BENCHMARK SUMMARY")
    print("=" * 90)
    print(f"{'Dataset':<16} {'Win':>5} {'ms':>7} {'Clips':>6} "
          f"{'Prec':>6} {'Rec':>6} {'F1':>6} {'Acc':>6} {'RTF':>7}")
    print("-" * 90)

    for _, row in summary_df.iterrows():
        print(
            f"{row['dataset']:<16} "
            f"{int(row['window_size']):>5} "
            f"{row['latency_ms']:>7.1f} "
            f"{int(row['n_clips']):>6} "
            f"{row['mean_precision']:>6.3f} "
            f"{row['mean_recall']:>6.3f} "
            f"{row['mean_f1']:>6.3f} "
            f"{row['mean_accuracy']:>6.3f} "
            f"{row['mean_rtf']:>7.1f}x"
        )
    print("=" * 90)
    print("Metrics: MIDI-rounded (nearest semitone), ±50-cent tolerance window")
    print("RTF: real-time factor (audio_duration / processing_time; higher = faster)")
