"""
GOAT (Guitar One-note Annotation Tool) dataset adapter — PLACEHOLDER.

GOAT provides single-note guitar recordings with precise onset, offset, and
pitch annotations (including string/fret information).

To integrate:
1. Obtain the dataset from the original authors or repository.
2. Place data under <root>/.
3. Implement __iter__ following the pattern in guitarset.py.

Reference:
    Wiggins & Kim, "Guitar Tablature Estimation with a Convolutional Neural
    Network", ISMIR 2019.

Expected directory layout (to be defined by integrator):
    <root>/
        audio/        # *.wav files
        annotations/  # annotation files (format TBD)
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .base import BaseDataset, DatasetSample


class GOATDataset(BaseDataset):
    """Placeholder loader for the GOAT dataset."""

    NAME        = "GOAT"
    DESCRIPTION = "Wiggins & Kim 2019 — Guitar One-note Annotation Tool (not yet integrated)"

    def is_available(self) -> bool:
        # TODO: update this check once the dataset is integrated
        return False

    def __iter__(self) -> Iterator[DatasetSample]:
        raise NotImplementedError(
            "GOAT dataset is not yet integrated.\n"
            "See benchmark/datasets/goat.py for instructions."
        )
