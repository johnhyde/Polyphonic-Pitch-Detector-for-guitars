"""
GuitarSet dataset adapter.

GuitarSet (Xi et al., 2018) provides 360 guitar recordings with precise
per-string pitch annotations.

Download:
    https://zenodo.org/record/3371780

Expected directory layout after extracting:
    <root>/
        annotation/            # *.jams files
        audio_mono-pickup_mix/ # *.wav  files  (recommended — smallest mono set)

The annotations use the "note_midi" namespace: each note event carries an onset
time, duration, and fractional MIDI note number (includes pitch bend cents).
We round to the nearest integer MIDI note because the benchmark only cares about
semitone-level accuracy.

Reference times are placed at the *centre* of each annotation time frame so they
align cleanly with the windowed detector output.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Iterator

import numpy as np

from .base import BaseDataset, DatasetSample

# Audio sub-directory names in priority order (smallest first).
_AUDIO_SUBDIRS = [
    "audio_mono-pickup_mix",
    "audio_mono-mic",
    "audio_hex-pickup_original",
    "audio_hex-pickup_debleeded",
    "audio",  # fallback if user places wavs directly
]


class GuitarSetDataset(BaseDataset):
    """
    Loader for the GuitarSet dataset.

    Parameters
    ----------
    root : str | Path
        Path to the extracted GuitarSet root directory.
    frame_size : float
        Duration of each reference annotation frame in seconds (default 0.01 s
        = 10 ms).  ref_times are placed at the centres of these frames.
    max_clips : int | None
        If set, stop after yielding this many clips (useful for quick tests).
    audio_subdir : str | None
        Override which audio sub-directory to use.
    """

    NAME        = "GuitarSet"
    DESCRIPTION = "Xi et al. 2018 — 360 annotated guitar recordings"

    def __init__(
        self,
        root: str | Path,
        frame_size: float   = 0.01,
        max_clips: int | None = None,
        audio_subdir: str | None = None,
    ):
        super().__init__(root)
        self.frame_size  = frame_size
        self.max_clips   = max_clips
        self._audio_subdir = audio_subdir

    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        if not self.root.is_dir():
            return False
        ann_dir = self.root / "annotation"
        return ann_dir.is_dir() and any(ann_dir.glob("*.jams"))

    # ------------------------------------------------------------------
    def _audio_dir(self) -> Path | None:
        if self._audio_subdir:
            p = self.root / self._audio_subdir
            return p if p.is_dir() else None
        for name in _AUDIO_SUBDIRS:
            p = self.root / name
            if p.is_dir():
                return p
        return None

    # ------------------------------------------------------------------
    def __iter__(self) -> Iterator[DatasetSample]:
        try:
            import jams
            import librosa
        except ImportError as exc:
            raise ImportError(
                "GuitarSetDataset requires 'jams' and 'librosa'. "
                "Install with: pip install jams librosa"
            ) from exc

        ann_dir   = self.root / "annotation"
        audio_dir = self._audio_dir()

        jams_files = sorted(ann_dir.glob("*.jams"))
        if not jams_files:
            return

        count = 0
        for jams_path in jams_files:
            if self.max_clips is not None and count >= self.max_clips:
                break

            # ---- locate matching audio ----
            stem = jams_path.stem
            wav_path = None
            if audio_dir is not None:
                # Try exact stem match first, then common suffixes added by
                # GuitarSet audio variants (e.g. "_mix", "_mic")
                for name_stem in [stem, stem + "_mix", stem + "_mic"]:
                    for suffix in (".wav", ".flac", ".mp3"):
                        candidate = audio_dir / (name_stem + suffix)
                        if candidate.exists():
                            wav_path = candidate
                            break
                    if wav_path:
                        break

            if wav_path is None:
                warnings.warn(
                    f"GuitarSet: no audio found for {stem}, skipping.",
                    stacklevel=2,
                )
                continue

            # ---- load audio ----
            try:
                audio, sr = librosa.load(str(wav_path), sr=None, mono=True)
            except Exception as exc:
                warnings.warn(f"GuitarSet: failed to load {wav_path}: {exc}", stacklevel=2)
                continue

            audio = audio.astype(np.float64)

            # ---- load annotations ----
            try:
                jam = jams.load(str(jams_path))
            except Exception as exc:
                warnings.warn(f"GuitarSet: failed to load {jams_path}: {exc}", stacklevel=2)
                continue

            ref_times, ref_freqs = self._build_ref_frames(jam, len(audio) / sr)
            if ref_times is None:
                warnings.warn(f"GuitarSet: no note_midi annotations in {jams_path}, skipping.", stacklevel=2)
                continue

            yield DatasetSample(
                audio       = audio,
                sample_rate = int(sr),
                ref_times   = ref_times,
                ref_freqs   = ref_freqs,
                name        = stem,
            )
            count += 1

    # ------------------------------------------------------------------
    def _build_ref_frames(
        self, jam, duration: float
    ) -> tuple[np.ndarray, list[np.ndarray]] | tuple[None, None]:
        """
        Convert JAMS note_midi annotations into a dense frame grid.

        Returns (ref_times, ref_freqs) suitable for mir_eval.multipitch.evaluate().
        ref_times  : 1-D array of frame centres
        ref_freqs  : list of 1-D arrays (Hz) — one per frame centre
        """
        anns = jam.search(namespace="note_midi")
        if not anns:
            return None, None

        # Build a list of (onset, offset, midi_note) across all strings
        events: list[tuple[float, float, int]] = []
        for ann in anns:
            for obs in ann.data:
                # obs.time and obs.duration may be float (seconds) or timedelta
                # depending on jams version
                t = obs.time
                d = obs.duration
                onset  = t.total_seconds() if hasattr(t, "total_seconds") else float(t)
                dur    = d.total_seconds() if hasattr(d, "total_seconds") else float(d)
                offset = onset + dur
                midi_raw = float(obs.value)
                midi_int = round(midi_raw)
                events.append((onset, offset, midi_int))

        if not events:
            return None, None

        # Dense frame grid at self.frame_size resolution
        n_frames  = max(1, int(np.ceil(duration / self.frame_size)))
        ref_times = (np.arange(n_frames) + 0.5) * self.frame_size  # frame centres
        ref_freqs = [np.array([], dtype=np.float64) for _ in range(n_frames)]

        for onset, offset, midi in events:
            # Hz for this note
            hz = 2.0 ** ((midi - 69) / 12.0) * 440.0
            i_start = max(0, int(np.floor(onset  / self.frame_size)))
            i_end   = min(n_frames, int(np.ceil( offset / self.frame_size)))
            for i in range(i_start, i_end):
                ref_freqs[i] = np.append(ref_freqs[i], hz)

        return ref_times, ref_freqs

    # ------------------------------------------------------------------
    def __len__(self) -> int:
        ann_dir = self.root / "annotation"
        if not ann_dir.is_dir():
            return 0
        return sum(1 for _ in ann_dir.glob("*.jams"))
