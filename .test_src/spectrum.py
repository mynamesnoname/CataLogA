"""FITS spectrum I/O.

Drop-in replacement for FORMA's NPZ-based ``load_spectrum()`` /
``read_spectrum_region()`` — works directly on DESI coadd FITS files.

DESI coadd files have three cameras (B / R / Z) stored as separate HDUs.
A "spectrum" here is the concatenation of all three, keyed by CAMERA.

Typical usage::

    from .test_src.spectrum import load_coadd_spectrum, read_spectrum_region

    sp = load_coadd_spectrum(coadd_path, targetid)
    # sp = {"B": (wave, flux, ivar), "R": (wave, flux, ivar), "Z": (wave, flux, ivar)}

    roi = read_spectrum_region(sp, 4700, 4900)
"""

import numpy as np
from astropy.io import fits


def _load_camera(hdul, cam, row):
    w = hdul[f"{cam}_WAVELENGTH"].data.astype(float)
    f = hdul[f"{cam}_FLUX"].data[row].astype(float)
    iv = hdul[f"{cam}_IVAR"].data[row].astype(float)
    m = hdul[f"{cam}_MASK"].data[row]
    bad = (iv <= 0) | (m != 0)
    f[bad] = np.nan
    iv[bad] = 0.0
    return w, f, iv


def load_coadd_spectrum(coadd_path: str, targetid: int):
    """Load B/R/Z spectra for one TARGETID from a DESI coadd FITS file.

    Returns ``dict[str, tuple]`` mapping camera letter to
    ``(wavelength, flux, ivar)``.
    """
    with fits.open(coadd_path, memmap=True) as h:
        fm = h["FIBERMAP"].data
        row = int(np.where(fm["TARGETID"] == targetid)[0][0])
        return {c: _load_camera(h, c, row) for c in "BRZ"}


def read_spectrum_region(
    spectrum: dict,
    wl_min: float,
    wl_max: float,
    stride: int = 1,
):
    """Read a raw wavelength slice of a loaded spectrum.

    Parameters
    ----------
    spectrum : dict
        Output of ``load_coadd_spectrum()``.
    wl_min, wl_max : float
        Wavelength range of interest (Å).
    stride : int
        Downsampling step.

    Returns
    -------
    dict with ``wl_range``, ``n``, ``wl``, ``fl``.
    """
    all_wl, all_fl = [], []
    for cam in "BRZ":
        w, f, _ = spectrum[cam]
        m = (w >= wl_min) & (w <= wl_max)
        all_wl.append(w[m])
        all_fl.append(f[m])

    if not all_wl:
        return {"wl_range": [wl_min, wl_max], "n": 0, "wl": [], "fl": []}

    wl_cat = np.concatenate(all_wl)
    fl_cat = np.concatenate(all_fl)
    idx = np.argsort(wl_cat)
    wl_cat, fl_cat = wl_cat[idx], fl_cat[idx]
    wl_cat, fl_cat = wl_cat[::stride], fl_cat[::stride]

    return {
        "wl_range": [wl_min, wl_max],
        "n": len(wl_cat),
        "wl": [round(float(w), 3) for w in wl_cat],
        "fl": [round(float(f), 4) for f in fl_cat],
    }


def merged_spectrum(spectrum: dict):
    """Concatenate B/R/Z into a single (wavelength, flux, ivar) triple."""
    all_w, all_f, all_iv = [], [], []
    for cam in "BRZ":
        w, f, iv = spectrum[cam]
        all_w.append(w); all_f.append(f); all_iv.append(iv)
    w = np.concatenate(all_w); f = np.concatenate(all_f); iv = np.concatenate(all_iv)
    idx = np.argsort(w)
    return w[idx], f[idx], iv[idx]


def load_redrock_info(redrock_path: str, targetid: int):
    """Return redshift metadata for one TARGETID from a redrock FITS file."""
    with fits.open(redrock_path, memmap=True) as h:
        zs = h["REDSHIFTS"].data
        fm = h["FIBERMAP"].data
        row = int(np.where(zs["TARGETID"] == targetid)[0][0])
        return {
            "targetid": int(targetid),
            "z": float(zs["Z"][row]),
            "zerr": float(zs["ZERR"][row]),
            "zwarn": int(zs["ZWARN"][row]),
            "chi2": float(zs["CHI2"][row]),
            "deltachi2": float(zs["DELTACHI2"][row]),
            "spectype": str(zs["SPECTYPE"][row]).strip(),
            "subtype": str(zs["SUBTYPE"][row]).strip(),
            "desi_target": int(fm["DESI_TARGET"][row]),
            "bgs_target": int(fm["BGS_TARGET"][row]),
        }
