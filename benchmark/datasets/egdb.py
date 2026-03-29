"""
EGDB (Electric Guitar Database) dataset adapter — PLACEHOLDER.

The EGDB dataset contains recordings of individual electric guitar notes across
multiple pickup positions, playing styles, and strings with precise MIDI pitch
ground truth.

To integrate:
1. Obtain the dataset (contact dataset authors or institutional access).
2. Place audio files and annotations under <root>/.
3. Implement __iter__ following the same pattern as GuitarSetDataset.

Reference:
    Kehling et al., "Automatic Tablature Transcription of Electric Guitar
    Recordings by Estimation of Score- and Instrument-Related Parameters",
    DAFx 2014.

Expected directory layout (to be defined by integrator):
    <root>/
        audio/    # *.wav files
        labels/   # annotation files (format TBD)
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .base import BaseDataset, DatasetSample


class EGDBDataset(BaseDataset):
    """Placeholder loader for the EGDB dataset."""

    NAME        = "EGDB"
    DESCRIPTION = "Kehling et al. 2014 — Electric Guitar Database (not yet integrated)"

    def is_available(self) -> bool:
        # TODO: update this check once the dataset is integrated
        return False

    def __iter__(self) -> Iterator[DatasetSample]:
        raise NotImplementedError(
            "EGDB dataset is not yet integrated.\n"
            "See benchmark/datasets/egdb.py for instructions."
        )
