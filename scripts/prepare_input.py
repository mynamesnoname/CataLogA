#!/usr/bin/env python
"""Prepare input directory by symlinking DESI repeat-observation pairs.

Reads ``discrepant_pairs_abs_dz_ge_0.01.csv`` (or a single targetid on the
command line) and populates ``{INPUT_DIR}/{targetid}/`` with symlinks::

    {targetid}/
    ├── coadd-A.fits   → {DATA_ROOT}/spectro/loa/tiles/cumulative/{tile}/.../coadd-*.fits
    ├── redrock-A.fits  → .../redrock-*.fits
    ├── coadd-B.fits
    └── redrock-B.fits

Usage::

    # Single target
    python scripts/prepare_input.py 39628250216924756

    # All 41 discrepant pairs from CSV
    python scripts/prepare_input.py --all

    # Dry-run (print what would be created)
    python scripts/prepare_input.py --all --dry-run
"""

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_triplet(spec_str: str):
    """Parse "(tileid, night, petal)" → (tileid, night, petal)."""
    s = spec_str.strip("()")
    parts = [p.strip() for p in s.split(",")]
    return int(parts[0]), int(parts[1]), int(parts[2])


def find_fits(data_root: str, tileid: int, night: int, petal: int, prefix: str):
    """Find a DESI coadd/redrock FITS file by (tile, night, petal)."""
    pattern = f"{prefix}-{petal}-{tileid}-thru{night}.fits"
    tiles_dir = os.path.join(data_root, "spectro", "loa", "tiles", "cumulative")
    path = os.path.join(tiles_dir, str(tileid), str(night), pattern)
    if os.path.isfile(path):
        return path
    raise FileNotFoundError(f"Cannot find {pattern} under {tiles_dir}")


def prepare_target(input_dir: str, data_root: str, targetid: int,
                   spec_a: tuple, spec_b: tuple, dry_run: bool = False):
    """Symlink coadd + redrock for one target."""
    out = os.path.join(input_dir, str(targetid))

    if dry_run:
        print(f"[dry-run] mkdir {out}")
    else:
        os.makedirs(out, exist_ok=True)

    for label, (tile, night, petal) in [("A", spec_a), ("B", spec_b)]:
        coadd = find_fits(data_root, tile, night, petal, "coadd")
        redrock = find_fits(data_root, tile, night, petal, "redrock")

        for dst, src in [(f"coadd-{label}.fits", coadd),
                         (f"redrock-{label}.fits", redrock)]:
            dst_path = os.path.join(out, dst)
            if dry_run:
                print(f"[dry-run] ln -s {src} → {dst_path}")
            else:
                if os.path.islink(dst_path) or os.path.exists(dst_path):
                    os.remove(dst_path)
                os.symlink(os.path.abspath(src), dst_path)
                print(f"  {dst} → {os.path.abspath(src)}")


def main():
    parser = argparse.ArgumentParser(description="Prepare CataLogA input directories")
    parser.add_argument("targetid", nargs="?", type=int, help="Single TARGETID")
    parser.add_argument("--all", action="store_true", help="Process all 41 pairs from CSV")
    parser.add_argument("--dry-run", action="store_true", help="Print actions only")
    parser.add_argument("--input-dir", default=os.environ.get("INPUT_DIR", "input"))
    parser.add_argument("--data-root", default=os.environ.get("DATA_ROOT", ".data/test_catas"))
    args = parser.parse_args()

    if not args.targetid and not args.all:
        parser.print_help()
        sys.exit(1)

    pairs = []

    if args.targetid:
        # Look up from CSV
        csv_path = os.path.join(
            PROJECT_ROOT, "output", "catastrophe_spectra",
            "discrepant_pairs_abs_dz_ge_0.01.csv",
        )
        import csv
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                if int(row["targetid"]) == args.targetid:
                    pairs.append(row)
                    break
        if not pairs:
            print(f"TARGETID {args.targetid} not found in CSV")
            sys.exit(1)

    if args.all:
        csv_path = os.path.join(
            PROJECT_ROOT, "output", "catastrophe_spectra",
            "discrepant_pairs_abs_dz_ge_0.01.csv",
        )
        import csv
        with open(csv_path, newline="") as f:
            pairs = list(csv.DictReader(f))

    for row in pairs:
        tid = int(row["targetid"])
        spec_a = parse_triplet(row["spec1fits"])
        spec_b = parse_triplet(row["spec2fits"])
        print(f"\nTARGETID {tid}  (z1={row['z1']}, z2={row['z2']}, |Δz|={row['abs_dz']})")
        try:
            prepare_target(args.input_dir, args.data_root, tid, spec_a, spec_b, args.dry_run)
        except FileNotFoundError as e:
            print(f"  SKIP: {e}")


if __name__ == "__main__":
    main()
