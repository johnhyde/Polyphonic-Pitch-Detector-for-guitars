#!/usr/bin/env python3
"""
run_benchmark.py — Entry point for the polyphonic pitch detection benchmark.

Usage examples
--------------
# Run with default settings (all available datasets, default window sizes):
    python benchmark/run_benchmark.py

# Specify dataset roots explicitly:
    python benchmark/run_benchmark.py \
        --guitarset /path/to/guitarset \
        --egdb      /path/to/egdb \
        --goat      /path/to/goat \
        --guitar-techs /path/to/guitar-techs

# Only test specific window sizes (in samples):
    python benchmark/run_benchmark.py --windows 256 512 960 2048 4096

# Quick test (limit clips per dataset):
    python benchmark/run_benchmark.py --max-clips 5

# Save results:
    python benchmark/run_benchmark.py --out results/

# Use 48 kHz sample rate (matches C++ RUN_AT_48KHZ build):
    python benchmark/run_benchmark.py --sample-rate 48000
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow running from repo root or from benchmark/
_here = Path(__file__).resolve().parent
if str(_here.parent) not in sys.path:
    sys.path.insert(0, str(_here.parent))

import numpy as np
import pandas as pd

from benchmark.datasets import (
    GuitarSetDataset,
    EGDBDataset,
    GOATDataset,
    GuitarTECHSDataset,
)
from benchmark.evaluate import run_benchmark, print_summary


# ── default dataset roots: check environment variables first, then common paths ──
_DEFAULT_ROOTS = {
    "guitarset":    os.environ.get("GUITARSET_ROOT",    "/home/user/datasets/guitarset"),
    "egdb":         os.environ.get("EGDB_ROOT",         "/home/user/datasets/egdb"),
    "goat":         os.environ.get("GOAT_ROOT",         "/home/user/datasets/goat"),
    "guitar_techs": os.environ.get("GUITAR_TECHS_ROOT", "/home/user/datasets/guitar_techs"),
}

# ── default window sizes to sweep ───────────────────────────────────────────────
_DEFAULT_WINDOWS = [256, 512, 960, 1024, 2048, 4096, 8192]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Benchmark the polyphonic pitch detector against labelled guitar datasets.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Dataset roots
    p.add_argument("--guitarset",    default=_DEFAULT_ROOTS["guitarset"],
                   help="Path to extracted GuitarSet directory")
    p.add_argument("--egdb",         default=_DEFAULT_ROOTS["egdb"],
                   help="Path to EGDB dataset (placeholder — not yet integrated)")
    p.add_argument("--goat",         default=_DEFAULT_ROOTS["goat"],
                   help="Path to GOAT dataset (placeholder — not yet integrated)")
    p.add_argument("--guitar-techs", default=_DEFAULT_ROOTS["guitar_techs"],
                   dest="guitar_techs",
                   help="Path to Guitar-TECHS dataset (placeholder — not yet integrated)")

    # Detector configuration
    p.add_argument("--windows",      nargs="+", type=int, default=_DEFAULT_WINDOWS,
                   metavar="N",
                   help="Window sizes in samples to sweep (default: %(default)s)")
    p.add_argument("--threshold",    type=float, default=0.001,
                   help="Energy threshold for note-on detection (default: %(default)s)")
    p.add_argument("--sample-rate",  type=float, default=44100.0, dest="sample_rate",
                   help="Detector sample rate in Hz (default: %(default)s). "
                        "Audio will be resampled to this rate if needed.")

    # Dataset control
    p.add_argument("--max-clips",    type=int, default=None, dest="max_clips",
                   metavar="N",
                   help="Limit clips per dataset (useful for quick tests)")

    # Output
    p.add_argument("--out",          default=None,
                   help="Directory to write CSV results (clip_results.csv, summary.csv)")
    p.add_argument("--quiet",        action="store_true",
                   help="Suppress progress output")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # ── assemble datasets ────────────────────────────────────────────────────
    datasets = [
        ("GuitarSet",    GuitarSetDataset(args.guitarset,    max_clips=args.max_clips)),
        ("EGDB",         EGDBDataset(args.egdb)),
        ("GOAT",         GOATDataset(args.goat)),
        ("Guitar-TECHS", GuitarTECHSDataset(args.guitar_techs)),
    ]

    verbose = not args.quiet
    if verbose:
        print("Polyphonic Pitch Detection Benchmark")
        print("=" * 50)
        for name, ds in datasets:
            status = "available" if ds.is_available() else "NOT AVAILABLE"
            print(f"  {name:<16}: {status}")
        print()
        windows_ms = [f"{w} ({1000.0*w/args.sample_rate:.1f} ms)" for w in args.windows]
        print(f"Window sizes : {', '.join(windows_ms)}")
        print(f"Threshold    : {args.threshold}")
        print(f"Sample rate  : {args.sample_rate:.0f} Hz")
        print()

    # ── run ─────────────────────────────────────────────────────────────────
    clip_df, summary_df = run_benchmark(
        datasets     = datasets,
        window_sizes = args.windows,
        threshold    = args.threshold,
        sample_rate  = args.sample_rate,
        verbose      = verbose,
    )

    # ── display ─────────────────────────────────────────────────────────────
    if not summary_df.empty:
        print_summary(summary_df)
    else:
        print("\nNo datasets were available. See --help for setup instructions.")
        print("To download GuitarSet:  python benchmark/download_datasets.py --guitarset")
        return 1

    # ── save ────────────────────────────────────────────────────────────────
    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        clip_path    = out_dir / "clip_results.csv"
        summary_path = out_dir / "summary.csv"
        clip_df.to_csv(clip_path,    index=False)
        summary_df.to_csv(summary_path, index=False)
        if verbose:
            print(f"\nResults saved to {out_dir}/")

    return 0


if __name__ == "__main__":
    sys.exit(main())
