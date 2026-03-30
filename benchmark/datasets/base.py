"""
Abstract base class for guitar dataset loaders used in the pitch-detection benchmark.

Each dataset must yield DatasetSample objects that contain:
  - audio       : 1-D float64 numpy array of mono audio samples
  - sample_rate : int
  - ref_times   : 1-D float64 array of reference annotation times (seconds)
  - ref_freqs   : list of 1-D float64 arrays; ref_freqs[i] contains all active
                  frequencies (Hz) at ref_times[i]  — suitable for mir_eval.multipitch
  - name        : human-readable identifier (filename / clip id)
"""

from __future__ import annotations

import abc
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import numpy as np


@dataclass
class DatasetSample:
    """One labelled audio clip ready for evaluation."""

    audio: np.ndarray            # shape (N,), dtype float64, mono, normalised
    sample_rate: int
    ref_times: np.ndarray        # shape (T,), seconds
    ref_freqs: list[np.ndarray]  # len T; each element is an array of Hz values
    name: str = ""

    # ------------------------------------------------------------------ helpers
    def duration(self) -> float:
        return len(self.audio) / self.sample_rate

    def num_frames(self) -> int:
        return len(self.ref_times)


class BaseDataset(abc.ABC):
    """
    Minimal interface every dataset adapter must implement.

    Subclasses must set:
        NAME        : str  — short identifier used in reports
        DESCRIPTION : str  — one-line human description
    """

    NAME: str        = "base"
    DESCRIPTION: str = ""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Return True if the dataset root exists and looks valid."""

    @abc.abstractmethod
    def __iter__(self) -> Iterator[DatasetSample]:
        """Yield DatasetSample objects one at a time."""

    def __len__(self) -> int:
        """Override to return the number of clips (optional)."""
        raise NotImplementedError

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def midi_to_hz(midi: float) -> float:
        return 2.0 ** ((midi - 69.0) / 12.0) * 440.0

    @staticmethod
    def hz_to_midi(hz: float) -> float:
        return 12.0 * np.log2(hz / 440.0) + 69.0

    @staticmethod
    def round_to_midi(hz: float) -> int:
        """Round a frequency in Hz to the nearest MIDI note number."""
        return round(12.0 * np.log2(hz / 440.0) + 69.0)
