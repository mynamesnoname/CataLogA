"""CataLogA test tools — ported from FORMA for the CataLogA workflow.

Modules
-------
lines      — rest-frame line tables + predict_lines()
spectrum   — DESI coadd FITS I/O
fitting    — Gaussian peak/doublet fitting
features   — CWT (Ricker wavelet) feature detection
detect     — [O II] unresolved-doublet slope-change detection
evaluate   — hypothesis evaluation + comparison
"""

from .lines import load_lines, predict_lines, WIDTH_3SIGMA, DOUBLET_PARAMS
from .spectrum import (
    load_coadd_spectrum, read_spectrum_region, merged_spectrum,
    load_redrock_info,
)
from .fitting import fit_peak, fit_doublet
from .features import find_features_cwt
from .detect import detect_oii_slope_change
from .evaluate import evaluate_hypothesis, compare_hypotheses
