"""DESI coadd spectrum I/O with arm overlap cleaning.

Leverages ``vi_utils.load_and_clean_spectrum()`` (adapted from FORMA's
``VI.py:_load_spectrum_from_fits()``) for mask-bit quality cuts and
arm boundary overlap removal.

Provides the same public API as the older ``.test_src/spectrum.py``:
``load_coadd_spectrum()``, ``read_spectrum_region()``, ``merged_spectrum()``,
``load_redrock_info()``.
"""

import numpy as np
from astropy.io import fits
from cataloga.tools.vi_utils import load_and_clean_spectrum


def load_coadd_spectrum(coadd_path: str, targetid: int):
    """Load B/R/Z spectra for one TARGETID with arm overlap cleaning.

    Returns ``dict[str, tuple]`` mapping camera letter to
    ``(wavelength, flux, ivar)``, plus a ``_cleaned`` key with the merged
    triple and a ``_masked_regions`` key.
    """
    result = load_and_clean_spectrum(coadd_path, targetid)
    per_cam = result["per_camera"]
    out = {cam: per_cam[cam] for cam in per_cam}
    out["_merged"] = result["merged"]
    out["_masked_regions"] = result["masked_regions"]
    return out


def read_spectrum_region(spectrum: dict, wl_min: float, wl_max: float,
                          stride: int = 1):
    """Read a raw wavelength slice of a loaded spectrum.

    Uses the merged (overlap-cleaned) spectrum when available.
    """
    if "_merged" in spectrum:
        w_all, f_all, _ = spectrum["_merged"]
    else:
        all_w, all_f = [], []
        for cam in "BRZ":
            w, f, _ = spectrum[cam]
            all_w.append(w); all_f.append(f)
        w_all = np.concatenate(all_w); f_all = np.concatenate(all_f)
        idx = np.argsort(w_all); w_all = w_all[idx]; f_all = f_all[idx]

    mask = (w_all >= wl_min) & (w_all <= wl_max)
    w = w_all[mask][::stride]; fl = f_all[mask][::stride]
    good = np.isfinite(fl)
    w, fl = w[good], fl[good]

    return {
        "wl_range": [wl_min, wl_max],
        "n": len(w),
        "wl": [round(float(x), 3) for x in w],
        "fl": [round(float(x), 4) for x in fl],
    }


def merged_spectrum(spectrum: dict):
    """Return (wavelength, flux, ivar) for the full overlap-cleaned spectrum."""
    if "_merged" in spectrum:
        return spectrum["_merged"]
    all_w, all_f, all_iv = [], [], []
    for cam in "BRZ":
        w, f, iv = spectrum[cam]
        all_w.append(w); all_f.append(f); all_iv.append(iv)
    w = np.concatenate(all_w); f = np.concatenate(all_f); iv = np.concatenate(all_iv)
    idx = np.argsort(w)
    return w[idx], f[idx], iv[idx]


def load_redrock_info(redrock_path: str, targetid: int):
    """Return redshift metadata for one TARGETID from a redrock FITS file."""
    import os
    import re
    with fits.open(redrock_path, memmap=True) as h:
        zs = h["REDSHIFTS"].data
        row = int(np.where(zs["TARGETID"] == targetid)[0][0])
        fm = h["FIBERMAP"].data
        # (tile, night, petal) are encoded in the standard DESI path:
        # .../cumulative/{tile}/{night}/redrock-{petal}-{tile}-thru{night}.fits
        # Resolve symlinks first (intermediate inputs are symlinks).
        tile = night = petal = "?"
        m = re.search(r"cumulative/(\d+)/(\d+)/redrock-(\d+)-",
                      os.path.realpath(redrock_path).replace(os.sep, "/"))
        if m:
            tile, night, petal = m.group(1), m.group(2), int(m.group(3))
        return {
            "targetid": int(targetid),
            "z": float(zs["Z"][row]),
            "zerr": float(zs["ZERR"][row]),
            "zwarn": int(zs["ZWARN"][row]),
            "chi2": float(zs["CHI2"][row]),
            "deltachi2": float(zs["DELTACHI2"][row]),
            "spectype": str(zs["SPECTYPE"][row]).strip(),
            "desi_target": int(fm["DESI_TARGET"][row]),
            "tile": tile, "night": night, "petal": petal,
        }
