"""
Guitar-TECHS dataset adapter — PLACEHOLDER.

Guitar-TECHS (Techniques and Extended CHordS) provides guitar recordings
annotated with playing techniques, chords, and per-note MIDI pitches, making it
well-suited for evaluating polyphonic detection under real-world playing
conditions.

To integrate:
1. Obtain the dataset (see the associated publication/repository).
2. Place data under <root>/.
3. Implement __iter__ following the pattern in guitarset.py.

Reference:
    Rocamora et al., "Guitar-TECHS: A Multi-Modal Dataset for Guitar
    Technique Recognition", SMC 2023 (or successor publication).

Expected directory layout (to be defined by integrator):
    <root>/
        audio/        # *.wav files
        annotations/  # annotation files (format TBD)
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .base import BaseDataset, DatasetSample


class GuitarTECHSDataset(BaseDataset):
    """Placeholder loader for the Guitar-TECHS dataset."""

    NAME        = "Guitar-TECHS"
    DESCRIPTION = "Rocamora et al. — Guitar-TECHS dataset (not yet integrated)"

    def is_available(self) -> bool:
        # TODO: update this check once the dataset is integrated
        return False

    def __iter__(self) -> Iterator[DatasetSample]:
        raise NotImplementedError(
            "Guitar-TECHS dataset is not yet integrated.\n"
            "See benchmark/datasets/guitar_techs.py for instructions."
        )
