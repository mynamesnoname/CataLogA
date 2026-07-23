"""Chebyshev continuum fitting — ported from FORMA ``utils/VI.py``.

Provides iterative continuum fitting with CWT-feature masking, then
CWT detection on the continuum-subtracted residual.
"""

import warnings

import numpy as np

try:
    from specutils import Spectrum as Spec1D
except ImportError:
    from specutils import Spectrum1D as Spec1D

SIGMA_TO_FWHM = 2.355  # FWHM = 2.355 × σ (Gaussian)


def select_chebyshev_degree(sp, min_degree=1, max_degree=10, verbose=False):
    """Auto-select the best Chebyshev polynomial degree.

    Criterion: low residual MAD + skewness close to 0.5 + complexity penalty.
    Ported from FORMA ``VI.py:select_chebyshev_degree``.
    """
    from scipy.stats import skew
    from specutils.fitting import fit_generic_continuum
    from astropy.modeling import models

    flux = sp.flux.value
    best_degree = min_degree
    best_score = np.inf

    for deg in range(min_degree, max_degree + 1):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                cf = fit_generic_continuum(sp, model=models.Chebyshev1D(degree=deg))
            res = flux - cf(sp.spectral_axis).value
            mask = np.abs(res) < np.percentile(np.abs(res), 95)
            rm = res[mask]
            res_skew = abs(skew(rm))
            res_mad = np.median(np.abs(rm - np.median(rm)))
            score = res_mad * 10.0 + (res_skew - 0.5) ** 2 * 5.0 + deg * 0.2
            if verbose:
                print(f"  degree={deg}: skew={res_skew:.4f}, MAD={res_mad:.4e}, score={score:.4f}")
            if score < best_score:
                best_score = score
                best_degree = deg
        except Exception as e:
            if verbose:
                print(f"  degree={deg}: fit failed - {e}")
    if verbose:
        print(f"Best degree: {best_degree}")
    return best_degree


def run_continuum_fitting_masked(
    wavelengths,
    flux,
    peaks=None,
    troughs=None,
    chebyshev_degree=None,
    chebyshev_min_degree=1,
    chebyshev_max_degree=10,
    verbose=False,
):
    """Fit a Chebyshev polynomial continuum, masking detected features.

    Features (peaks/troughs) are masked at ±3σ before fitting, so that
    real spectral lines don't bias the continuum estimate.

    Ported from FORMA ``VI.py:run_continuum_fitting_masked``.

    Parameters
    ----------
    wavelengths : array-like  (Å)
    flux : array-like
    peaks, troughs : list of dict, optional
        Must contain ``wavelength`` and ``FWHM_A`` keys.
    chebyshev_degree : int or None
        Fixed degree; if None, auto-selects via ``select_chebyshev_degree``.

    Returns
    -------
    continuum_dict : dict with keys wavelength, flux, chebyshev_degree
    residual_flux : ndarray  (flux - continuum)
    """
    from specutils.fitting import fit_generic_continuum
    from astropy.modeling import models
    import astropy.units as u

    wavelengths = np.asarray(wavelengths, dtype=np.float64)
    flux = np.asarray(flux, dtype=np.float64)

    # ── Build feature mask: exclude centre ±3σ of each feature ──
    fit_mask = np.ones(len(wavelengths), dtype=bool)

    all_features = []
    if peaks:
        all_features.extend(peaks)
    if troughs:
        all_features.extend(troughs)

    n_masked_pts = 0
    for feat in all_features:
        wl_center = feat.get("wavelength")
        fwhm_a = feat.get("FWHM_A")
        if wl_center is None or fwhm_a is None:
            continue
        sigma = fwhm_a / SIGMA_TO_FWHM
        lo, hi = wl_center - 3 * sigma, wl_center + 3 * sigma
        in_region = (wavelengths >= lo) & (wavelengths <= hi)
        n_masked_pts += int(in_region.sum())
        fit_mask &= ~in_region

    # Also mask NaN/Inf pixels (arm overlap zones produce NaN flux values)
    finite_mask = np.isfinite(flux)
    fit_mask &= finite_mask

    n_fit_pts = int(fit_mask.sum())
    print(f"[Continuum] {len(all_features)} features, masked {n_masked_pts} px, "
          f"fitting {n_fit_pts}/{len(wavelengths)} px")

    if n_fit_pts < 20:
        print("[Continuum] <20 usable points, falling back to finite-only fit")
        fit_mask = np.isfinite(flux)

    wave_fit = wavelengths[fit_mask]
    flux_fit = flux[fit_mask]

    # ── Auto-select degree + fit ──
    sp_fit = Spec1D(flux=flux_fit * u.Jy, spectral_axis=wave_fit * u.AA)

    if chebyshev_degree is None:
        chebyshev_degree = select_chebyshev_degree(
            sp_fit, min_degree=chebyshev_min_degree,
            max_degree=chebyshev_max_degree, verbose=verbose,
        )

    print(f"[Continuum] Chebyshev degree = {chebyshev_degree}")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        cf = fit_generic_continuum(
            sp_fit, model=models.Chebyshev1D(degree=chebyshev_degree))

    continuum_flux = cf(wavelengths * u.AA).value
    residual_flux = flux - continuum_flux

    continuum_dict = {
        "wavelength": wavelengths.tolist(),
        "flux": continuum_flux.tolist(),
        "chebyshev_degree": chebyshev_degree,
        "n_masked_features": len(all_features),
        "n_masked_points": n_masked_pts,
    }

    return continuum_dict, residual_flux
