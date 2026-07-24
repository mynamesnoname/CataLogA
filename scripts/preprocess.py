#!/usr/bin/env python
"""Preprocess DESI repeat-observation data for CataLogA.

Three steps:

1. Scan ``DATA_ROOT`` for all redrock FITS, find TARGETIDs appearing
   in multiple observations, compute |Δz| for each pair, output CSV.
2. Filter by ``DZ_THRESHOLD``, create symlinks in ``INTERMEDIATE_DIR``.
3. Write ``targets.txt`` listing all TARGETIDs sorted by |Δz| desc.

Usage::

    python scripts/preprocess.py
    python scripts/preprocess.py --force   # regenerate CSV even if exists

Environment (.env):
    DATA_ROOT, INTERMEDIATE_DIR, OUTPUT_DIR, DZ_THRESHOLD
"""

import argparse
import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
except ImportError:
    pass

from astropy.io import fits

DATA_ROOT = os.environ.get("DATA_ROOT", ".data/test_catas")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")
INTERMEDIATE_DIR = os.environ.get("INTERMEDIATE_DIR", "input")
DZ_THRESHOLD = float(os.environ.get("DZ_THRESHOLD", "0.01"))


def scan_redrock_files(data_root: str):
    """Walk data_root, yield (tile, night, petal, path) for each redrock FITS."""
    base = os.path.join(data_root, "spectro", "loa", "tiles", "cumulative")
    if not os.path.isdir(base):
        print(f"[ERROR] Data root not found: {base}")
        sys.exit(1)

    for tile in sorted(os.listdir(base)):
        tile_dir = os.path.join(base, tile)
        if not os.path.isdir(tile_dir):
            continue
        for night in sorted(os.listdir(tile_dir)):
            night_dir = os.path.join(tile_dir, night)
            if not os.path.isdir(night_dir):
                continue
            for fname in sorted(os.listdir(night_dir)):
                if fname.startswith("redrock-") and fname.endswith(".fits"):
                    # redrock-{petal}-{tile}-thru{night}.fits
                    parts = fname.replace(".fits", "").split("-")
                    petal = parts[1]
                    path = os.path.join(night_dir, fname)
                    yield (tile, night, petal, path)


def read_redrock_targets(fits_path: str) -> dict:
    """Read FIBERMAP + REDSHIFTS HDUs, return {targetid: row_dict}."""
    results = {}
    try:
        with fits.open(fits_path, memmap=True) as hdul:
            # FIBERMAP has TARGETID, OBJTYPE
            fb = hdul["FIBERMAP"].data
            tids = fb["TARGETID"]
            objtypes = fb["OBJTYPE"]

            # REDSHIFTS has Z, ZERR, ZWARN, SPECTYPE, DELTACHI2
            rz = hdul["REDSHIFTS"].data
            z_arr = rz["Z"]
            zerr_arr = rz["ZERR"]
            zwarn_arr = rz["ZWARN"]
            sptype_arr = rz["SPECTYPE"]
            dchi2_arr = rz["DELTACHI2"]

            for i in range(len(tids)):
                tid = int(tids[i])
                if tid <= 0:
                    continue
                objtype = objtypes[i].strip() if isinstance(objtypes[i], str) else str(objtypes[i])
                if objtype != "TGT":
                    continue  # skip sky fibers etc.
                results[tid] = {
                    "z": float(z_arr[i]),
                    "zerr": float(zerr_arr[i]),
                    "zwarn": int(zwarn_arr[i]),
                    "spectype": sptype_arr[i].strip() if isinstance(sptype_arr[i], str) else str(sptype_arr[i]),
                    "dchi2": float(dchi2_arr[i]),
                }
    except Exception as e:
        print(f"  [WARN] Failed to read {fits_path}: {e}")
    return results


def find_repeat_pairs(data_root: str) -> list[dict]:
    """Find all TARGETIDs with >=2 observations, compute |Δz| for each pair."""
    # Collect all observations indexed by TARGETID
    tid_to_obs = defaultdict(list)  # {targetid: [(tile,night,petal,path,row), ...]}

    print(f"\nScanning: {data_root}/spectro/loa/tiles/cumulative/")
    count = 0
    for tile, night, petal, path in scan_redrock_files(data_root):
        targets = read_redrock_targets(path)
        for tid, row in targets.items():
            tid_to_obs[tid].append((tile, night, petal, path, row))
        count += 1
        sys.stdout.write(f"\r  {count} redrock files scanned, {len(tid_to_obs)} unique TARGETIDs ...")
        sys.stdout.flush()
    print()

    # For each TARGETID with >=2 observations, enumerate all unique pairs
    pairs = []
    for tid, obs_list in tid_to_obs.items():
        if len(obs_list) < 2:
            continue
        # Only keep pairs from DIFFERENT (tile,night,petal) tuples
        for i in range(len(obs_list)):
            for j in range(i + 1, len(obs_list)):
                # Skip identical observations
                key_i = (obs_list[i][0], obs_list[i][1], obs_list[i][2])
                key_j = (obs_list[j][0], obs_list[j][1], obs_list[j][2])
                if key_i == key_j:
                    continue

                ri = obs_list[i][4]
                rj = obs_list[j][4]
                abs_dz = abs(ri["z"] - rj["z"])

                pairs.append({
                    "targetid": tid,
                    "z1": ri["z"], "z2": rj["z"],
                    "RedrockType1": ri["spectype"], "RedrockType2": rj["spectype"],
                    "zwarn1": ri["zwarn"], "zwarn2": rj["zwarn"],
                    "dchi2_1": ri["dchi2"], "dchi2_2": rj["dchi2"],
                    "fits1": f"({key_i[0]},{key_i[1]},{key_i[2]})",
                    "fits2": f"({key_j[0]},{key_j[1]},{key_j[2]})",
                    "abs_dz": abs_dz,
                    "tile1": key_i[0], "night1": key_i[1], "petal1": key_i[2],
                    "tile2": key_j[0], "night2": key_j[1], "petal2": key_j[2],
                })

    pairs.sort(key=lambda p: p["abs_dz"], reverse=True)
    return pairs


def write_csv(pairs: list[dict], out_path: str):
    """Write pairs to CSV, sorted by |Δz| desc."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fields = ["targetid", "z1", "RedrockType1", "zwarn1", "dchi2_1", "fits1",
              "tile1", "night1", "petal1",
              "z2", "RedrockType2", "zwarn2", "dchi2_2", "fits2",
              "tile2", "night2", "petal2", "abs_dz"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for i, p in enumerate(pairs):
            p["index"] = i
            w.writerow(p)
    print(f"  CSV: {len(pairs)} pairs → {out_path}")


def create_symlinks(pairs: list[dict], data_root: str, intermediate_dir: str,
                    dz_threshold: float):
    """Create symlinks for pairs with |Δz| >= dz_threshold."""
    base = os.path.join(data_root, "spectro", "loa", "tiles", "cumulative")
    os.makedirs(intermediate_dir, exist_ok=True)

    targetids = []
    for p in pairs:
        if p["abs_dz"] < dz_threshold:
            continue
        tid = p["targetid"]
        out_dir = os.path.join(intermediate_dir, str(tid))
        os.makedirs(out_dir, exist_ok=True)

        for label, tile, night, petal in [
            ("A", p["tile1"], p["night1"], p["petal1"]),
            ("B", p["tile2"], p["night2"], p["petal2"]),
        ]:
            for prefix in ["coadd", "redrock"]:
                fname = f"{prefix}-{petal}-{tile}-thru{night}.fits"
                src = os.path.join(base, tile, night, fname)
                dst = os.path.join(out_dir, f"{prefix}-{label}.fits")
                if os.path.islink(dst) or os.path.exists(dst):
                    os.remove(dst)
                if os.path.exists(src):
                    os.symlink(os.path.abspath(src), dst)
                else:
                    print(f"  [WARN] Source not found: {src}")

        targetids.append(tid)

    # Write targets.txt
    txt_path = os.path.join(intermediate_dir, "targets.txt")
    with open(txt_path, "w") as f:
        for tid in targetids:
            f.write(f"{tid}\n")

    n_total = len(pairs)
    n_above = len(targetids)
    print(f"  Symlinks: {n_above}/{n_total} pairs with |Δz| >= {dz_threshold}")
    print(f"  Target list: {txt_path}")


def main():
    parser = argparse.ArgumentParser(description="CataLogA preprocessing")
    parser.add_argument("--force", action="store_true", help="Regenerate CSV")
    parser.add_argument("--data-root", default=DATA_ROOT)
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    parser.add_argument("--intermediate-dir", default=INTERMEDIATE_DIR)
    parser.add_argument("--dz-threshold", type=float, default=DZ_THRESHOLD)
    args = parser.parse_args()

    csv_path = os.path.join(args.output_dir, "discrepant_pairs.csv")

    # Step 1: Scan and build CSV
    if os.path.exists(csv_path) and not args.force:
        print(f"CSV exists, loading: {csv_path}")
        pairs = []
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pairs.append(dict(row))
                for k in ("abs_dz", "z1", "z2", "dchi2_1", "dchi2_2"):
                    pairs[-1][k] = float(pairs[-1][k])
                for k in ("zwarn1", "zwarn2", "targetid"):
                    pairs[-1][k] = int(pairs[-1][k])
                if "tile1" not in pairs[-1] or not pairs[-1].get("tile1"):
                    # Legacy CSV without tile/night/petal columns — recover
                    # them from the "(tile,night,petal)" fits strings.
                    for sfx in ("1", "2"):
                        t, n, p_ = pairs[-1][f"fits{sfx}"].strip("()").split(",")
                        pairs[-1][f"tile{sfx}"] = t
                        pairs[-1][f"night{sfx}"] = n
                        pairs[-1][f"petal{sfx}"] = p_
    else:
        pairs = find_repeat_pairs(args.data_root)
        write_csv(pairs, csv_path)

    total = len(pairs)
    n_both_zero = sum(1 for p in pairs if p["zwarn1"] == 0 and p["zwarn2"] == 0)
    print(f"\n{total} pairs total, {n_both_zero} with ZWARN=0/0 (strict catastrophes)")

    # Step 2: Create symlinks
    create_symlinks(pairs, args.data_root, args.intermediate_dir, args.dz_threshold)

    print(f"\nDone. To run the pipeline:")
    print(f"  TARGETID=all python scripts/run_pipeline.py")
    print(f"  TARGETID=tail-5 python scripts/run_pipeline.py")


if __name__ == "__main__":
    main()
