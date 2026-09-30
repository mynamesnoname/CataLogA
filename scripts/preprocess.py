#!/usr/bin/env python
"""Preprocess DESI repeat-observation data for CataLogA.

Four steps:

1. Scan ``DATA_ROOT`` for all redrock FITS, find TARGETIDs appearing
   in multiple observations, compute |Δz| for each pair, output
   ``repeat_pairs.csv`` — EVERY repeat-observation pair found, agreeing
   or not (most agree; this is not a catastrophe list).
2. Select the final scientific sample from that table — tracer-dependent
   |Δz| threshold AND ZWARN=0/0 (Redrock confident on both exposures, yet
   they disagree — a "strict catastrophe") — output ``catastrophic_pairs.csv``.
3. Create symlinks in ``INTERMEDIATE_DIR`` for each catastrophic pair.
4. Write ``targets.txt`` listing those TARGETIDs sorted by |Δz| desc.

Usage::

    python scripts/preprocess.py
    python scripts/preprocess.py --force   # regenerate repeat_pairs.csv even if exists

Environment (.env):
    DATA_ROOT, INTERMEDIATE_DIR, OUTPUT_DIR, DZ_THRESHOLD_QSO, DZ_THRESHOLD_GALAXY

Catastrophe threshold is tracer-dependent: Redrock doesn't report a target's
survey class (BGS/LRG/ELG), only its fitted SPECTYPE, so a pair is treated as
a QSO pair (higher threshold — QSO redshifts are intrinsically less precise)
if either side's RedrockType is "QSO"; otherwise the tighter galaxy threshold
applies. ZWARN=0/0 is required on top of that (matches DESI's own "good
redshift" quality cut) — a pair failing this is Redrock correctly flagging
its own uncertainty (most commonly bit 2, SMALL_DELTA_CHI2: a degenerate
fit), not a confident-but-wrong catastrophe.
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
# QSO redshifts are fit from broad lines and are intrinsically less precise
# than galaxy redshifts (narrow lines) — a higher |Δz| is needed before a QSO
# pair counts as a genuine catastrophe rather than normal fit scatter.
# 0.03 ~ 10,000 km/s; 0.003 ~ 1,000 km/s.
DZ_THRESHOLD_QSO = float(os.environ.get("DZ_THRESHOLD_QSO", "0.03"))
DZ_THRESHOLD_GALAXY = float(os.environ.get("DZ_THRESHOLD_GALAXY", "0.003"))

# ── DESI targeting bitmasks (desi_mask / bgs_mask, main survey) ───────────
# https://github.com/desihub/desitarget/blob/main/py/desitarget/data/targetmask.yaml
# These are the pre-observation SELECTION class, distinct from SPECTYPE
# (Redrock's post-fit classification) — a target can carry multiple bits
# (e.g. selected as both ELG and QSO) since the classes aren't exclusive.
_DESI_TARGET_LRG = 2**0
_DESI_TARGET_ELG = 2**1
_DESI_TARGET_QSO = 2**2
_DESI_TARGET_BGS_ANY = 2**60
_BGS_TARGET_FAINT = 2**0
_BGS_TARGET_BRIGHT = 2**1
_BGS_TARGET_WISE = 2**2
_BGS_TARGET_FAINT_HIP = 2**3
# Lyα QSOs aren't a separate targeting bit — it's the QSO class with a
# post-hoc redshift cut, conventionally z > 2.1 for the Lyα forest sample.
_LYA_Z_MIN = 2.1


def _decode_tracer(desi_target: int, bgs_target: int, z: float) -> dict:
    """Decode DESI targeting bitmasks into a tracer classification.

    Returns individual booleans (a target can be multiple classes at once)
    plus a single priority-ordered ``tracer`` label for convenience:
    QSO_LYA > QSO > LRG > ELG > BGS > OTHER (OTHER = none of the above bits
    set, e.g. an MWS/secondary-program target).
    """
    is_lrg = bool(desi_target & _DESI_TARGET_LRG)
    is_elg = bool(desi_target & _DESI_TARGET_ELG)
    is_qso = bool(desi_target & _DESI_TARGET_QSO)
    is_bgs = bool(desi_target & _DESI_TARGET_BGS_ANY)
    is_lya = is_qso and z is not None and z > _LYA_Z_MIN

    bgs_subclass = ""
    if is_bgs:
        sub = []
        if bgs_target & _BGS_TARGET_BRIGHT:
            sub.append("BRIGHT")
        if bgs_target & _BGS_TARGET_FAINT:
            sub.append("FAINT")
        if bgs_target & _BGS_TARGET_WISE:
            sub.append("WISE")
        if bgs_target & _BGS_TARGET_FAINT_HIP:
            sub.append("FAINT_HIP")
        bgs_subclass = "+".join(sub)

    if is_lya:
        tracer = "QSO_LYA"
    elif is_qso:
        tracer = "QSO"
    elif is_lrg:
        tracer = "LRG"
    elif is_elg:
        tracer = "ELG"
    elif is_bgs:
        tracer = "BGS"
    else:
        tracer = "OTHER"

    return {
        "tracer": tracer,
        "is_lrg": is_lrg, "is_elg": is_elg, "is_qso": is_qso,
        "is_bgs": is_bgs, "is_lya": is_lya, "bgs_subclass": bgs_subclass,
    }


def _dz_threshold_for_pair(p: dict) -> float:
    """Tracer-dependent catastrophe threshold for one pair."""
    if p["RedrockType1"] == "QSO" or p["RedrockType2"] == "QSO":
        return DZ_THRESHOLD_QSO
    return DZ_THRESHOLD_GALAXY


def _resolve_path(p: str) -> str:
    """Resolve *p* to an absolute path.

    Absolute paths pass through unchanged; relative paths are anchored at
    the repository root (not the CWD), so the scripts work from anywhere.
    """
    if os.path.isabs(p):
        return p
    return os.path.abspath(os.path.join(PROJECT_ROOT, p))


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
            # FIBERMAP has TARGETID, OBJTYPE, and the targeting bitmasks
            fb = hdul["FIBERMAP"].data
            tids = fb["TARGETID"]
            objtypes = fb["OBJTYPE"]
            desi_target_arr = fb["DESI_TARGET"]
            bgs_target_arr = fb["BGS_TARGET"]

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
                z = float(z_arr[i])
                results[tid] = {
                    "z": z,
                    "zerr": float(zerr_arr[i]),
                    "zwarn": int(zwarn_arr[i]),
                    "spectype": sptype_arr[i].strip() if isinstance(sptype_arr[i], str) else str(sptype_arr[i]),
                    "dchi2": float(dchi2_arr[i]),
                    **_decode_tracer(int(desi_target_arr[i]), int(bgs_target_arr[i]), z),
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
                # Fractional redshift offset, mean-normalized (order-independent,
                # unlike normalizing by z_min): |z_A - z_B| / (1 + (z_A + z_B)/2)
                abs_dz = abs(ri["z"] - rj["z"]) / (1 + (ri["z"] + rj["z"]) / 2)

                # Targeting class is a property of the TARGET, not the
                # exposure — it should be identical between repeats. Prefer
                # the non-"OTHER" side if they ever disagree (e.g. is_lya
                # depends on the per-exposure fitted z, so it can legitimately
                # differ between a correct and a catastrophic fit).
                tracer_row = ri if ri["tracer"] != "OTHER" else rj

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
                    "tracer": tracer_row["tracer"],
                    "is_lrg": tracer_row["is_lrg"], "is_elg": tracer_row["is_elg"],
                    "is_qso": tracer_row["is_qso"], "is_bgs": tracer_row["is_bgs"],
                    "bgs_subclass": tracer_row["bgs_subclass"],
                    "is_lya_1": ri["is_lya"], "is_lya_2": rj["is_lya"],
                })

    pairs.sort(key=lambda p: p["abs_dz"], reverse=True)
    return pairs


C_KM_S = 299792.458  # speed of light, km/s


def write_csv(pairs: list[dict], out_path: str, extra_fields: list[str] = None):
    """Write pairs to CSV, sorted by |Δz| desc."""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fields = ["targetid", "z1", "RedrockType1", "zwarn1", "dchi2_1", "fits1",
              "tile1", "night1", "petal1",
              "z2", "RedrockType2", "zwarn2", "dchi2_2", "fits2",
              "tile2", "night2", "petal2", "abs_dz",
              "tracer", "is_lrg", "is_elg", "is_qso", "is_bgs", "bgs_subclass",
              "is_lya_1", "is_lya_2"] + (extra_fields or [])
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for i, p in enumerate(pairs):
            p["index"] = i
            w.writerow(p)
    print(f"  CSV: {len(pairs)} pairs → {out_path}")


def select_catastrophic_pairs(pairs: list[dict],
                              dz_threshold_qso: float,
                              dz_threshold_galaxy: float) -> list[dict]:
    """Select the final scientific sample: tracer-dependent |Δz| AND ZWARN=0/0.

    ZWARN=0 on both sides matches DESI's own "good redshift" quality cut used
    in BAO/clustering catalogs. Requiring it here restricts the candidate
    pool to *strict* catastrophes — Redrock was CONFIDENT on both repeat
    exposures, yet they still disagree — the failure mode that can silently
    bias downstream cosmology, since nothing in Redrock's own output would
    flag it. A ZWARN!=0 pair (most commonly bit 2, SMALL_DELTA_CHI2 — the
    fit is already degenerate) would never enter a science sample anyway, so
    it isn't a "catastrophe" in the scientifically relevant sense: it's
    Redrock correctly reporting it wasn't sure.
    """
    selected = []
    n_qso = n_galaxy = n_zwarn_excluded = 0
    for p in pairs:
        is_qso = p["RedrockType1"] == "QSO" or p["RedrockType2"] == "QSO"
        threshold = dz_threshold_qso if is_qso else dz_threshold_galaxy
        if p["abs_dz"] < threshold:
            continue
        if not (p["zwarn1"] == 0 and p["zwarn2"] == 0):
            n_zwarn_excluded += 1
            continue
        if is_qso:
            n_qso += 1
        else:
            n_galaxy += 1
        # abs_dz is already the mean-normalized fractional offset, so the
        # velocity form is a direct scaling — no further (1+z) division.
        p["dv"] = C_KM_S * p["abs_dz"]
        selected.append(p)
    print(f"  Catastrophic: {len(selected)}/{len(pairs)} pairs above threshold and ZWARN=0/0 "
          f"({n_qso} QSO @ |Δz|>={dz_threshold_qso}, "
          f"{n_galaxy} galaxy @ |Δz|>={dz_threshold_galaxy}, "
          f"{n_zwarn_excluded} excluded for ZWARN≠0)")
    return selected


def create_symlinks(pairs: list[dict], data_root: str, intermediate_dir: str):
    """Create symlinks in *intermediate_dir* for each (already-filtered) pair."""
    base = os.path.join(data_root, "spectro", "loa", "tiles", "cumulative")
    os.makedirs(intermediate_dir, exist_ok=True)

    targetids = []
    for p in pairs:
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

    print(f"  Symlinks: {len(targetids)} targetids → {intermediate_dir}")
    print(f"  Target list: {txt_path}")


def main():
    parser = argparse.ArgumentParser(description="CataLogA preprocessing")
    parser.add_argument("--force", action="store_true", help="Regenerate repeat_pairs.csv")
    parser.add_argument("--data-root", default=DATA_ROOT)
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    parser.add_argument("--intermediate-dir", default=INTERMEDIATE_DIR)
    parser.add_argument("--dz-threshold-qso", type=float, default=DZ_THRESHOLD_QSO)
    parser.add_argument("--dz-threshold-galaxy", type=float, default=DZ_THRESHOLD_GALAXY)
    args = parser.parse_args()
    args.data_root = _resolve_path(args.data_root)
    args.output_dir = _resolve_path(args.output_dir)
    args.intermediate_dir = _resolve_path(args.intermediate_dir)

    csv_path = os.path.join(args.output_dir, "repeat_pairs.csv")

    # Step 1: Scan and build the full repeat-pairs table (all pairs, unfiltered)
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
    print(f"\n{total} repeat pairs total, {n_both_zero} with ZWARN=0/0 (both fits confident)")

    # Step 2: Select candidate catastrophes from the repeat-pairs table
    catastrophic = select_catastrophic_pairs(
        pairs, args.dz_threshold_qso, args.dz_threshold_galaxy)
    write_csv(catastrophic, os.path.join(args.output_dir, "catastrophic_pairs.csv"),
              extra_fields=["dv"])

    # Step 3: Create symlinks for the selected catastrophic pairs
    create_symlinks(catastrophic, args.data_root, args.intermediate_dir)

    print(f"\nDone. To run the pipeline:")
    print(f"  TARGETID=all python scripts/run_pipeline.py")
    print(f"  TARGETID=tail-5 python scripts/run_pipeline.py")


if __name__ == "__main__":
    main()
