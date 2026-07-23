"""VisualInterpreter — pure-numerical preprocessing for downstream agents.

Loads a DESI coadd spectrum from one observation, runs CWT feature
detection, and collects redshift hypotheses from both repeat-observation
redrock files.

Output dict feeds directly into SH_A → SH_B → FA → HS.
"""

from cataloga.tools.spectrum import load_coadd_spectrum, merged_spectrum, load_redrock_info
from cataloga.tools.features import find_features_cwt


def run_vi(
    coadd_path: str,
    redrock_path_a: str,
    redrock_path_b: str,
    targetid: int,
    *,
    cwt_snr_thresh: float = 5.0,
    cwt_min_ridge_length: int = 2,
    cwt_n_scales: int = 24,
    cwt_min_width: float = 1.0,
    cwt_max_width: float = 80.0,
) -> dict:
    """Run VI: load spectrum → CWT → collect redrock hypotheses.

    Parameters
    ----------
    coadd_path : str
        Path to the coadd FITS to use as the reference spectrum.
        (Typically the higher-quality of the two repeat observations.)
    redrock_path_a, redrock_path_b : str
        Redrock FITS files from the two repeat observations.
    targetid : int
    cwt_snr_thresh : float
        CWT SNR threshold (default 5.0).
    cwt_min_ridge_length : int
        Minimum CWT ridge length (default 2).

    Returns
    -------
    dict with keys:
        spectrum : dict
            Per-camera B/R/Z dict from ``load_coadd_spectrum``.
        wl, fl, iv : ndarray
            Merged (overlap-cleaned) spectrum arrays.
        peaks, troughs : list[dict]
            CWT-detected emission / absorption features.
        masked_regions : list[tuple]
            Wavelength ranges masked as arm-overlap zones.
        redrock_a, redrock_b : dict
            Redrock metadata for each observation (z, ZWARN, SPECTYPE, chi2).
    """
    spectrum = load_coadd_spectrum(coadd_path, targetid)
    wl, fl, iv = merged_spectrum(spectrum)

    peaks, troughs = find_features_cwt(
        wl, fl,
        snr_thresh=cwt_snr_thresh,
        min_ridge_length=cwt_min_ridge_length,
        n_scales=cwt_n_scales,
        min_scale=cwt_min_width,
        max_scale=cwt_max_width,
    )

    redrock_a = load_redrock_info(redrock_path_a, targetid)
    redrock_b = load_redrock_info(redrock_path_b, targetid)
    masked_regions = spectrum.get("_masked_regions", [])

    return {
        "spectrum": spectrum,
        "wl": wl, "fl": fl, "iv": iv,
        "peaks": peaks, "troughs": troughs,
        "masked_regions": masked_regions,
        "redrock_a": redrock_a,
        "redrock_b": redrock_b,
    }
