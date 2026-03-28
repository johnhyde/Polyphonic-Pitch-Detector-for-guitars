#!/usr/bin/env python3
"""
download_datasets.py — Download publicly available guitar datasets for benchmarking.

Currently supported
-------------------
GuitarSet (Xi et al., 2018)
    Zenodo record: https://zenodo.org/record/3371780
    Files downloaded: annotation.zip (~39 MB) + audio_mono-pickup_mix.zip (~683 MB)

Placeholders (manual download required)
-------------------
EGDB        — contact authors (Kehling et al., DAFx 2014)
GOAT        — see Wiggins & Kim, ISMIR 2019
Guitar-TECHS — see Rocamora et al., SMC 2023

Usage
-----
    # Download GuitarSet to the default location:
    python benchmark/download_datasets.py --guitarset

    # Download to a custom directory:
    python benchmark/download_datasets.py --guitarset --guitarset-dir /data/guitarset

    # Download only annotations (no audio):
    python benchmark/download_datasets.py --guitarset --no-audio
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlretrieve, urlopen
from urllib.error import URLError

try:
    from tqdm import tqdm
    _TQDM = True
except ImportError:
    _TQDM = False


# ── Zenodo URLs ──────────────────────────────────────────────────────────────
GUITARSET_ZENODO_ID = "3371780"
GUITARSET_BASE_URL  = f"https://zenodo.org/record/{GUITARSET_ZENODO_ID}/files"

GUITARSET_FILES = {
    "annotation":            ("annotation.zip",            39_132_574),
    "audio_mono-pickup_mix": ("audio_mono-pickup_mix.zip", 683_145_360),
    "audio_mono-mic":        ("audio_mono-mic.zip",        656_927_981),
}


# ── helpers ──────────────────────────────────────────────────────────────────

class _ProgressBar:
    """Simple download progress reporter using tqdm if available."""

    def __init__(self, total: int, desc: str):
        self._total  = total
        self._seen   = 0
        self._desc   = desc
        if _TQDM:
            self._bar = tqdm(total=total, unit="B", unit_scale=True, desc=desc)
        else:
            self._bar = None

    def update(self, chunk: int):
        self._seen += chunk
        if self._bar:
            self._bar.update(chunk)
        else:
            pct = 100 * self._seen / self._total if self._total else 0
            mb  = self._seen / 1_048_576
            print(f"\r  {self._desc}: {mb:.1f} MB ({pct:.0f}%)", end="", flush=True)

    def close(self):
        if self._bar:
            self._bar.close()
        else:
            print()


def _download_file(url: str, dest: Path, expected_size: int = 0) -> bool:
    """Download url to dest with progress.  Returns True on success."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")

    progress = _ProgressBar(expected_size or 1, dest.name)
    try:
        def reporthook(block_num, block_size, total_size):
            if total_size > 0 and progress._total == 1:
                progress._total = total_size
                if progress._bar:
                    progress._bar.total = total_size
            progress.update(block_size)

        urlretrieve(url, str(tmp), reporthook=reporthook)
        progress.close()
        tmp.rename(dest)
        return True
    except (URLError, OSError) as exc:
        progress.close()
        print(f"\n  ERROR: {exc}")
        if tmp.exists():
            tmp.unlink()
        return False


def _extract_zip(zip_path: Path, dest_dir: Path, subdir_name: str) -> bool:
    """Extract zip to dest_dir/subdir_name/.  Returns True on success."""
    out = dest_dir / subdir_name
    out.mkdir(parents=True, exist_ok=True)
    print(f"  Extracting {zip_path.name} → {out} ...", flush=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(out)
        return True
    except zipfile.BadZipFile as exc:
        print(f"  ERROR extracting: {exc}")
        return False


# ── GuitarSet ─────────────────────────────────────────────────────────────────

def download_guitarset(
    dest_dir: Path,
    include_audio: bool = True,
    audio_variant: str  = "audio_mono-pickup_mix",
    keep_zips: bool     = False,
) -> bool:
    """
    Download and extract GuitarSet from Zenodo.

    Parameters
    ----------
    dest_dir      : target directory
    include_audio : if False, only download annotations
    audio_variant : which audio zip to fetch (default: mono pickup mix, smallest)
    keep_zips     : keep the zip files after extraction
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading GuitarSet to {dest_dir}")

    variants = ["annotation"]
    if include_audio:
        if audio_variant not in GUITARSET_FILES:
            print(f"  Unknown audio variant '{audio_variant}'. "
                  f"Choose from: {list(GUITARSET_FILES)}")
            return False
        variants.append(audio_variant)

    success = True
    for key in variants:
        filename, expected_size = GUITARSET_FILES[key]
        url      = f"{GUITARSET_BASE_URL}/{filename}"
        zip_path = dest_dir / filename

        if zip_path.exists() and zip_path.stat().st_size > 0:
            print(f"  {filename} already exists, skipping download.")
        else:
            print(f"  Downloading {filename} ({expected_size / 1e6:.0f} MB) ...")
            if not _download_file(url, zip_path, expected_size):
                success = False
                continue

        # Extract
        subdir = key  # e.g. "annotation" or "audio_mono-pickup_mix"
        target = dest_dir / subdir
        if target.exists() and any(target.iterdir()):
            print(f"  {subdir}/ already extracted, skipping.")
        else:
            if not _extract_zip(zip_path, dest_dir, subdir):
                success = False
                continue

        # GuitarSet zips often contain a single top-level subdirectory —
        # flatten if needed (e.g. annotation/annotation/*.jams → annotation/*.jams)
        _flatten_single_subdir(dest_dir / subdir)

        if not keep_zips:
            zip_path.unlink(missing_ok=True)

    if success:
        print(f"\nGuitarSet ready at: {dest_dir}")
        ann_count = len(list((dest_dir / "annotation").glob("*.jams")))
        print(f"  Annotation files: {ann_count}")
        if include_audio:
            wav_count = len(list((dest_dir / audio_variant).glob("*.wav")))
            print(f"  Audio files     : {wav_count}")

    return success


def _flatten_single_subdir(path: Path):
    """
    If a directory contains exactly one subdirectory and no files,
    move the subdirectory's contents up one level.
    e.g.  annotation/annotation/foo.jams  →  annotation/foo.jams
    """
    if not path.is_dir():
        return
    children = list(path.iterdir())
    if len(children) == 1 and children[0].is_dir():
        inner = children[0]
        # Move each item in inner up to path
        for item in inner.iterdir():
            shutil.move(str(item), str(path / item.name))
        inner.rmdir()


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Download guitar datasets for the pitch detection benchmark.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    p.add_argument("--guitarset",        action="store_true",
                   help="Download GuitarSet")
    p.add_argument("--guitarset-dir",    default="/home/user/datasets/guitarset",
                   dest="guitarset_dir", metavar="DIR",
                   help="Target directory for GuitarSet (default: %(default)s)")
    p.add_argument("--no-audio",         action="store_false", dest="include_audio",
                   default=True,
                   help="Skip audio download (annotations only)")
    p.add_argument("--audio-variant",    default="audio_mono-pickup_mix",
                   dest="audio_variant",
                   choices=list(GUITARSET_FILES.keys()),
                   help="Which GuitarSet audio variant to download")
    p.add_argument("--keep-zips",        action="store_true", dest="keep_zips",
                   help="Keep zip files after extraction")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.guitarset:
        print("Nothing to do. Use --guitarset to download GuitarSet.")
        print("Run with --help for options.")
        return 0

    ok = True
    if args.guitarset:
        ok = download_guitarset(
            dest_dir      = Path(args.guitarset_dir),
            include_audio = args.include_audio,
            audio_variant = args.audio_variant,
            keep_zips     = args.keep_zips,
        ) and ok

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
