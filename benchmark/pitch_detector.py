"""
Python reimplementation of the C++ polyphonic pitch detector from cPdct.cpp/cPdct.h.

The algorithm uses a bank of first-order complex IIR resonators (one per semitone)
with Constant-Q bandwidth. Energy is accumulated over a window, then thresholded to
determine which MIDI notes are active.

Reference algorithm:
  "A Computationally Efficient Method for Polyphonic Pitch Estimation"
  Zhou, Reiss, Mattavelli, Zoia (2009)
"""

import time
import numpy as np

# --- Constants matching cPdct.h ---
FIRST_GUITAR_NOTE = 40   # E2, 82.407 Hz
LAST_GUITAR_NOTE  = 88   # E6, 1318.510 Hz
FIRST_NOTE_NUMBER = FIRST_GUITAR_NOTE - 1   # 39
LAST_NOTE_NUMBER  = LAST_GUITAR_NOTE  + 1   # 89
NUM_OF_RESONATOR  = LAST_NOTE_NUMBER - FIRST_NOTE_NUMBER + 1  # 51

DEFAULT_WINDOW_SIZE = 960    # 20 ms at 48 kHz, ~21.8 ms at 44.1 kHz
DEFAULT_THRESHOLD   = 0.001  # Energy threshold for note-on/off


def note_to_frequency(note: int) -> float:
    """Equal-temperament, A4 = 440 Hz."""
    return 2.0 ** ((note - 69) / 12.0) * 440.0


def build_resonator_coefficients(sample_rate: float = 44100.0):
    """
    Compute b0 (real scalar) and a1 (complex) for each of the 51 resonators.

    Matches cPdct::init() exactly:
        d = 2^(1/24)
        c = (2*d - 2) / (d + 1)
        omega   = 2*pi*f
        width   = 2*pi*f*c
        r_omega = width / pi
        a1 = exp((-r_omega + j*omega) / sample_rate)
        r  = exp(-r_omega / sample_rate)
        b0 = ((1 - r^2) / r) / sqrt(2)
    """
    d = 2.0 ** (1.0 / 24.0)
    c = (2.0 * d - 2.0) / (d + 1.0)

    b0 = np.zeros(NUM_OF_RESONATOR, dtype=np.float64)
    a1 = np.zeros(NUM_OF_RESONATOR, dtype=np.complex128)

    for i in range(NUM_OF_RESONATOR):
        note = i + FIRST_NOTE_NUMBER
        freq = note_to_frequency(note)
        omega   = 2.0 * np.pi * freq
        width   = 2.0 * np.pi * freq * c
        r_omega = width / np.pi

        a1[i] = np.exp((-r_omega + 1j * omega) / sample_rate)
        r      = np.exp(-r_omega / sample_rate)
        b0[i]  = ((1.0 - r * r) / r) / np.sqrt(2.0)

    return b0, a1


class PitchDetector:
    """
    Polyphonic pitch detector: faithful Python translation of cPdct.cpp.

    Parameters
    ----------
    sample_rate : float
        Audio sample rate in Hz (44100 or 48000).
    window_size : int
        Number of samples to accumulate before evaluating (default 960).
        Corresponds to WINDOW_SIZE in C++. Varying this is the primary lever
        for the accuracy-vs-latency trade-off.
    threshold : float
        Energy threshold for note-on detection (default 0.001).
        Corresponds to the literal `0.001` in doEnergyAnalysis().
    """

    def __init__(
        self,
        sample_rate: float = 44100.0,
        window_size: int   = DEFAULT_WINDOW_SIZE,
        threshold: float   = DEFAULT_THRESHOLD,
    ):
        self.sample_rate = sample_rate
        self.window_size = window_size
        self.threshold   = threshold

        self.b0, self.a1 = build_resonator_coefficients(sample_rate)
        self.reset()

    def reset(self):
        """Zero resonator state, energy accumulators, and frame counter."""
        self.state  = np.zeros(NUM_OF_RESONATOR, dtype=np.complex128)
        self.energy = np.zeros(NUM_OF_RESONATOR, dtype=np.float64)
        self.frame  = 0

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    def process_audio(self, audio: np.ndarray) -> list[tuple[float, list[int]]]:
        """
        Process a 1-D float64 audio array.

        Returns a list of (timestamp_seconds, [active_midi_notes]) tuples,
        one entry per completed window.  The timestamp is the time of the
        *last* sample in each window (i.e. the earliest moment the detector
        could have produced its output).

        The detector state persists across calls so you can stream audio in
        chunks.  Call reset() to start fresh.
        """
        results: list[tuple[float, list[int]]] = []

        # --- vectorised IIR across resonator dimension ---
        # state shape : (NUM_OF_RESONATOR,) complex
        # b0 shape    : (NUM_OF_RESONATOR,) float  (broadcast fine)
        state  = self.state
        energy = self.energy
        frame  = self.frame
        ws     = self.window_size
        thresh = self.threshold
        a1     = self.a1
        b0     = self.b0
        sr     = self.sample_rate

        for n, sample in enumerate(audio):
            state   = b0 * sample + a1 * state
            energy += (state.real ** 2 + state.imag ** 2) / ws
            frame  += 1

            if frame == ws:
                active = (np.where(energy > thresh)[0] + FIRST_NOTE_NUMBER).tolist()
                # timestamp = sample index of the last sample in this window
                # (we don't track absolute position here; caller must offset)
                results.append(active)
                energy = np.zeros(NUM_OF_RESONATOR, dtype=np.float64)
                frame  = 0

        self.state  = state
        self.energy = energy
        self.frame  = frame
        return results

    def process_audio_timed(self, audio: np.ndarray) -> tuple[list[list[int]], float]:
        """
        Same as process_audio but also returns wall-clock processing time (s).
        Useful for measuring throughput vs real-time ratio.
        """
        t0 = time.perf_counter()
        results = self.process_audio(audio)
        elapsed = time.perf_counter() - t0
        return results, elapsed

    # ------------------------------------------------------------------
    # Convenience: process and return per-window timestamps
    # ------------------------------------------------------------------

    def process_file(
        self, audio: np.ndarray, start_sample: int = 0
    ) -> list[tuple[float, list[int]]]:
        """
        Process audio, returning (time_seconds, [midi_notes]) pairs.

        start_sample lets you accumulate across multiple calls while
        keeping timestamps correct.
        """
        raw = self.process_audio(audio)
        ws  = self.window_size
        sr  = self.sample_rate
        return [
            ((start_sample + (i + 1) * ws) / sr, notes)
            for i, notes in enumerate(raw)
        ]

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def midi_to_hz(midi: int) -> float:
        return 2.0 ** ((midi - 69) / 12.0) * 440.0

    @staticmethod
    def hz_to_midi(hz: float) -> float:
        return 12.0 * np.log2(hz / 440.0) + 69.0

    @property
    def latency_ms(self) -> float:
        return 1000.0 * self.window_size / self.sample_rate

    @property
    def note_range(self) -> tuple[int, int]:
        return (FIRST_NOTE_NUMBER, LAST_NOTE_NUMBER)
