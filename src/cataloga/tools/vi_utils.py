"""VisualInterpreter utilities — ported from FORMA's ``utils/VI.py``.

Provides DESI FITS spectrum loading with arm overlap handling and quality masking.
Kept minimal: no PNG/OCR channel, no Redrock subprocess, no continuum fitting.
"""

import logging
import numpy as np
from astropy.io import fits

# ---------------------------------------------------------------------------
# Arm overlap detection (from FORMA usage.py)
# ---------------------------------------------------------------------------

# Default DESI arm configuration
DESI_ARM_NAMES = ["B", "R", "Z"]
DESI_ARM_WAVELENGTHS = [(3600, 5800), (5760, 7620), (7520, 9824)]


def find_overlap_regions(band_names, band_wavelengths):
    """Find all pairwise overlap regions between spectral bands.

    Parameters
    ----------
    band_names : list[str] — e.g. ["B", "R", "Z"]
    band_wavelengths : list[(float, float)] — wavelength range per band

    Returns
    -------
    dict[str, list[float, float]] — e.g. {"B-R": [5760, 5800], "R-Z": [7520, 7620]}
    """
    result = {}
    n = len(band_names)
    for i in range(n):
        for j in range(i + 1, n):
            start1, end1 = band_wavelengths[i]
            start2, end2 = band_wavelengths[j]
            overlap_start = max(start1, start2)
            overlap_end = min(end1, end2)
            if overlap_start < overlap_end:
                overlap_name = f"{band_names[i]}-{band_names[j]}"
                result[overlap_name] = [overlap_start, overlap_end]
    return result


# ---------------------------------------------------------------------------
# FITS spectrum loading — adapted from FORMA VI.py _load_spectrum_from_fits
# ---------------------------------------------------------------------------

def _load_per_camera(hdul, cam, row):
    """Load wavelength, flux, ivar, mask for one camera and one fiber row."""
    w = hdul[f"{cam}_WAVELENGTH"].data.astype(float)
    f = hdul[f"{cam}_FLUX"].data[row].astype(float)
    iv = hdul[f"{cam}_IVAR"].data[row].astype(float)
    mk = hdul[f"{cam}_MASK"].data[row].astype(int)
    return w, f, iv, mk


def _mask_bad_pixels(wave, flux, ivar, mask):
    """Apply SPECMASK quality cuts.  MASK≠0 or IVAR≤0 → NaN."""
    bad = (ivar <= 0) | (mask != 0)
    flux = flux.copy()
    ivar = ivar.copy()
    flux[bad] = np.nan
    ivar[bad] = 0.0
    return flux, ivar


def load_and_clean_spectrum(
    coadd_path: str,
    targetid: int,
    arm_names=None,
    arm_wavelengths=None,
):
    """Load a DESI coadd spectrum for one TARGETID and clean arm overlaps.

    This combines what was previously in ``spectrum.py:load_coadd_spectrum``
    with FORMA's arm overlap removal logic.

    Returns a dict with per-camera arrays (B/R/Z) AND a merged
    (wavelength, flux, ivar) triple with overlap regions averaged.
    """
    if arm_names is None:
        arm_names = DESI_ARM_NAMES
    if arm_wavelengths is None:
        arm_wavelengths = DESI_ARM_WAVELENGTHS

    with fits.open(coadd_path, memmap=True) as hdul:
        fm = hdul["FIBERMAP"].data
        row = int(np.where(fm["TARGETID"] == targetid)[0][0])

        per_cam = {}
        for cam in arm_names:
            w, f, iv, mk = _load_per_camera(hdul, cam, row)
            f, iv = _mask_bad_pixels(w, f, iv, mk)
            per_cam[cam] = (w, f, iv)

    # Find and clean overlap regions
    overlaps = find_overlap_regions(arm_names, arm_wavelengths)

    # Build merged array: concatenate all cameras, removing overlap duplicates.
    # In overlap zones, keep the camera with better median IVAR.
    all_w, all_f, all_iv = [], [], []

    for i, cam in enumerate(arm_names):
        w, f, iv = per_cam[cam]
        lo, hi = arm_wavelengths[i]

        # Determine if this camera's edges overlap with neighbors
        mask = np.ones(len(w), dtype=bool)
        for ov_name, (ov_lo, ov_hi) in overlaps.items():
            if cam in ov_name.split("-"):
                # Find which is the other camera in this overlap
                ov_cams = ov_name.split("-")
                other_cam = ov_cams[0] if ov_cams[1] == cam else ov_cams[1]
                other_idx = arm_names.index(other_cam)

                # Compare median IVAR — this camera keeps pixels where its IVAR
                # is higher than the other camera's IVAR at the same wavelength
                _, _, other_iv = per_cam[other_cam]
                med_iv_self = np.nanmedian(iv[(w >= ov_lo) & (w <= ov_hi)])
                med_iv_other = np.nanmedian(other_iv[(per_cam[other_cam][0] >= ov_lo) & (per_cam[other_cam][0] <= ov_hi)])

                if np.isfinite(med_iv_self) and np.isfinite(med_iv_other):
                    if med_iv_self < med_iv_other:
                        # This camera has worse IVAR — mask its overlap zone
                        mask[(w >= ov_lo) & (w <= ov_hi)] = False

        all_w.append(w[mask])
        all_f.append(f[mask])
        all_iv.append(iv[mask])

    w_merged = np.concatenate(all_w)
    f_merged = np.concatenate(all_f)
    iv_merged = np.concatenate(all_iv)
    idx = np.argsort(w_merged)

    # Remove duplicate wavelengths (rare, from stitching)
    w_merged = w_merged[idx]
    f_merged = f_merged[idx]
    iv_merged = iv_merged[idx]
    unique_mask = np.concatenate([[True], np.diff(w_merged) > 1e-6])
    w_merged = w_merged[unique_mask]
    f_merged = f_merged[unique_mask]
    iv_merged = iv_merged[unique_mask]

    # Build the masked_regions list for downstream agents
    masked_regions = []
    for ov_name, (ov_lo, ov_hi) in overlaps.items():
        masked_regions.append((ov_lo, ov_hi))

    return {
        "per_camera": per_cam,
        "merged": (w_merged, f_merged, iv_merged),
        "masked_regions": masked_regions,
        "overlaps": overlaps,
    }
