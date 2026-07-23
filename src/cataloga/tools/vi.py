"""VisualInterpreter — pure-numerical preprocessing for downstream agents.

Loads a DESI coadd spectrum, runs CWT feature detection (median-filter
continuum as in FORMA), then fits a Chebyshev continuum with CWT-detected
features masked out (FORMA Phase E).

Output dict feeds directly into SH_A → SH_B → FA → HS → RA.
"""

from cataloga.tools.spectrum import load_coadd_spectrum, merged_spectrum, load_redrock_info
from cataloga.tools.features import find_features_cwt
from cataloga.tools.continuum import run_continuum_fitting_masked


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
    """Run VI: load spectrum → CWT (median-filter) → Chebyshev continuum.

    FORMA order: Phase D CWT (median-filter residual) → Phase E Chebyshev
    continuum fitting with detected features masked.

    Returns
    -------
    dict with keys:
        spectrum, wl, fl, iv, peaks, troughs, masked_regions,
        continuum, redrock_a, redrock_b
    """
    spectrum = load_coadd_spectrum(coadd_path, targetid)
    wl, fl, iv = merged_spectrum(spectrum)

    # Phase D: CWT on median-filter residual (FORMA cwt_feature_finder.py:184)
    peaks, troughs = find_features_cwt(
        wl, fl,
        snr_thresh=cwt_snr_thresh,
        min_ridge_length=cwt_min_ridge_length,
        n_scales=cwt_n_scales,
        min_scale=cwt_min_width,
        max_scale=cwt_max_width,
    )

    # Phase E: Chebyshev continuum with detected features masked (FORMA VI.py:352)
    continuum, _ = run_continuum_fitting_masked(
        wl, fl, peaks=peaks, troughs=troughs,
    )

    redrock_a = load_redrock_info(redrock_path_a, targetid)
    redrock_b = load_redrock_info(redrock_path_b, targetid)
    masked_regions = spectrum.get("_masked_regions", [])

    return {
        "spectrum": spectrum,
        "wl": wl, "fl": fl, "iv": iv,
        "peaks": peaks, "troughs": troughs,
        "continuum": continuum,
        "masked_regions": masked_regions,
        "redrock_a": redrock_a,
        "redrock_b": redrock_b,
    }
