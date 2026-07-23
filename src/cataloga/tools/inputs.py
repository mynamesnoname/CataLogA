"""Resolve input directories for single-target and batch runs.

Input convention (one subdirectory per TARGETID)::

    {INPUT_DIR}/
    └── {targetid}/
        ├── coadd-A.fits      # first observation coadd
        ├── redrock-A.fits    # first observation redrock
        ├── coadd-B.fits      # second observation coadd
        └── redrock-B.fits    # second observation redrock

Symlinks are fine — no need to copy the original DESI files.
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class TargetInput:
    """One TARGETID with two repeat observations."""
    targetid: int
    coadd_a: str       # path to coadd FITS (observation A)
    redrock_a: str     # path to redrock FITS (observation A)
    coadd_b: str
    redrock_b: str

    def __repr__(self):
        return f"TargetInput({self.targetid})"


def load_target(input_dir: str, targetid: int) -> TargetInput:
    """Resolve input files for a single *targetid*.

    Raises ``FileNotFoundError`` if any of the four files are missing.
    """
    d = os.path.join(input_dir, str(targetid))

    def _require(stem: str) -> str:
        p = os.path.join(d, stem)
        if not os.path.exists(p):
            raise FileNotFoundError(f"Missing input file: {p}")
        return p

    return TargetInput(
        targetid=targetid,
        coadd_a=_require("coadd-A.fits"),
        redrock_a=_require("redrock-A.fits"),
        coadd_b=_require("coadd-B.fits"),
        redrock_b=_require("redrock-B.fits"),
    )


def list_targets(input_dir: str) -> list[int]:
    """List all TARGETIDs in the input directory.

    A valid target directory must contain at least ``coadd-A.fits``.
    """
    if not os.path.isdir(input_dir):
        return []
    tids = []
    for name in sorted(os.listdir(input_dir)):
        d = os.path.join(input_dir, name)
        if not os.path.isdir(d):
            continue
        if not os.path.isfile(os.path.join(d, "coadd-A.fits")):
            continue
        try:
            tids.append(int(name))
        except ValueError:
            pass
    return tids
