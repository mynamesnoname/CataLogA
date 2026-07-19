"""Gaussian line fitting on in-memory spectra.

Ported from FORMA's ``harness/tools.py`` — adapted to work directly on
(wavelength, flux) arrays (no NPZ intermediate).

Provides:
- ``fit_peak()`` — single Gaussian + linear baseline
- ``fit_doublet()`` — two Gaussians + linear baseline with doublet validation
- ``_gaussian_plus_linear()``, ``_doublet_model()`` — model functions
- ``_WIDTH_3SIGMA_MAP`` — default widths for line width classes
"""

import numpy as np
from scipy.optimize import curve_fit

# ---------------------------------------------------------------------------
# Default 3σ widths (same as FORMA)
# ---------------------------------------------------------------------------
WIDTH_3SIGMA = {"broad": 90.0, "narrow": 25.0, "both": 50.0, "absorption": 20.0}

# ---------------------------------------------------------------------------
# Model functions
# ---------------------------------------------------------------------------


def _gaussian_plus_linear(x, amp, center, sigma, slope, intercept):
    return amp * np.exp(-((x - center) ** 2) / (2 * sigma**2)) + slope * x + intercept


def _doublet_model(x, amp1, center1, sigma1, amp2, center2, sigma2, slope, intercept):
    g1 = amp1 * np.exp(-((x - center1) / sigma1) ** 2 / 2)
    g2 = amp2 * np.exp(-((x - center2) / sigma2) ** 2 / 2)
    return g1 + g2 + slope * x + intercept


# ---------------------------------------------------------------------------
# fit_peak
# ---------------------------------------------------------------------------


def fit_peak(
    wavelength,
    flux,
    center_guess: float,
    width_3sigma: float = 25.0,
    line_type: str = "emission",
    window_half: float = 200.0,
) -> dict:
    """Fit a Gaussian + linear baseline around ``center_guess``.

    Parameters
    ----------
    wavelength, flux : 1-D arrays
    center_guess : float
        Predicted observed wavelength (Å).
    width_3sigma : float
        Expected 3σ width in Å (broad=90, narrow=25, both=50, absorption=20).
    line_type : "emission" or "absorption"
        Constrains amplitude sign.
    window_half : float
        Half-width of the fitting window in Å.

    Returns
    -------
    dict with center, center_err, amplitude, sigma, fwhm, fwhm_km_s,
         delta_chi2_per_n, local_rms, local_snr, n_points, flags, message.
    """
    mask = (wavelength >= center_guess - window_half) & (wavelength <= center_guess + window_half)
    wl = wavelength[mask]
    fl = flux[mask]
    good = np.isfinite(fl)
    wl, fl = wl[good], fl[good]

    if len(wl) < 10:
        return _empty_result(len(wl), ["too_few_points"],
                             f"Only {len(wl)} points in window.")

    lin_coeffs = np.polyfit(wl, fl, 1)
    slope0, intercept0 = float(lin_coeffs[0]), float(lin_coeffs[1])
    flux_at_center = float(np.interp(center_guess, wl, fl))
    linear_at_center = slope0 * center_guess + intercept0
    amp0 = flux_at_center - linear_at_center

    if line_type == "absorption":
        amp0 = min(amp0, -1e-6)
        amp_lower, amp_upper = -np.inf, 0.0
    else:
        amp0 = max(amp0, 1e-6)
        amp_lower, amp_upper = 0.0, np.inf

    sigma0 = np.clip(width_3sigma / 3.0, 2.0, window_half / 2)
    p0 = [amp0, center_guess, sigma0, slope0, intercept0]
    bounds = (
        [amp_lower, center_guess - 50, 1.0, -np.inf, -np.inf],
        [amp_upper, center_guess + 50, window_half, np.inf, np.inf],
    )

    try:
        popt, pcov = curve_fit(
            _gaussian_plus_linear, wl, fl, p0=p0, bounds=bounds, maxfev=5000
        )
    except Exception as e:
        return _empty_result(len(wl), ["fit_failed"], f"curve_fit failed: {e}")

    return _build_peak_result(wl, fl, popt, pcov, center_guess, line_type)


def _build_peak_result(wl, fl, popt, pcov, center_guess, line_type):
    amp, center, sigma, slope, intercept = popt
    perr = np.sqrt(np.diag(pcov)) if pcov is not None else [None] * 5

    fitted = _gaussian_plus_linear(wl, *popt)
    linear_only = slope * wl + intercept
    residuals = fl - fitted

    local_rms = 1.4826 * np.median(np.abs(residuals - np.median(residuals)))
    if local_rms < 1e-10:
        local_rms = float(np.std(residuals)) or 1e-10

    n = len(wl)
    chi2_full = np.sum((residuals / local_rms) ** 2)
    chi2_linear = np.sum(((fl - linear_only) / local_rms) ** 2)
    delta_chi2_per_n = round(float((chi2_linear - chi2_full) / n), 3)
    local_snr = round(float(abs(amp) / local_rms), 2)
    fwhm = sigma * 2.35482
    fwhm_km_s = fwhm / center * 2.99792458e5 if center != 0 else None

    flags = []
    if abs(center - center_guess) > 50:
        flags.append("center_deviation_large")
    if delta_chi2_per_n < 0:
        flags.append("negative_delta_chi2")

    msg = (
        f"Fit {'OK' if not flags else 'warnings'}. "
        f"c={center:.2f}±{perr[1]:.3f}Å, amp={amp:.4f}, "
        f"FWHM={fwhm:.1f}Å ({fwhm_km_s:.0f} km/s), "
        f"S/N={local_snr:.1f}, Δχ²/n={delta_chi2_per_n:.1f}"
    )

    return {
        "center": round(float(center), 3),
        "center_err": round(float(perr[1]), 4) if perr[1] is not None else None,
        "amplitude": round(float(amp), 6),
        "amplitude_err": round(float(perr[0]), 6) if perr[0] is not None else None,
        "sigma": round(float(sigma), 3),
        "fwhm": round(float(fwhm), 3),
        "fwhm_km_s": round(float(fwhm_km_s), 1) if fwhm_km_s is not None else None,
        "delta_chi2_per_n": delta_chi2_per_n,
        "local_rms": round(float(local_rms), 6),
        "local_snr": local_snr,
        "n_points": n,
        "flags": flags,
        "message": msg,
    }


def _empty_result(n_points, flags, message):
    return {
        "center": None, "center_err": None,
        "amplitude": None, "amplitude_err": None,
        "sigma": None, "fwhm": None, "fwhm_km_s": None,
        "delta_chi2_per_n": None, "local_rms": None, "local_snr": None,
        "n_points": n_points, "flags": flags, "message": message,
    }


# ---------------------------------------------------------------------------
# fit_doublet
# ---------------------------------------------------------------------------


def fit_doublet(
    wavelength,
    flux,
    center_guess_1: float,
    center_guess_2: float,
    line_type: str = "emission",
    width_3sigma: float = 25.0,
    window_half: float = 300.0,
    separation_rest: float = None,
    separation_tolerance: float = 5.0,
    amp_ratio_expected: float = None,
) -> dict:
    """Fit two Gaussians + linear baseline around a close line pair.

    On failure, falls back to individual single-Gaussian fits.

    Returns
    -------
    dict with component_1, component_2, delta_chi2_per_n, local_rms, local_snr,
         separation_check, amp_ratio_check, n_points, flags, message.
    """
    mid = (center_guess_1 + center_guess_2) / 2.0
    half = max(window_half, abs(center_guess_2 - center_guess_1) * 2.0)
    mask = (wavelength >= mid - half) & (wavelength <= mid + half)
    wl = wavelength[mask]
    fl = flux[mask]
    good = np.isfinite(fl)
    wl, fl = wl[good], fl[good]

    if len(wl) < 20:
        return {
            "component_1": None, "component_2": None,
            "delta_chi2_per_n": None, "local_rms": None, "local_snr": None,
            "separation_check": None, "amp_ratio_check": None,
            "n_points": len(wl),
            "flags": ["too_few_points"],
            "message": f"Only {len(wl)} points in window.",
        }

    lin_coeffs = np.polyfit(wl, fl, 1)
    slope0, intercept0 = float(lin_coeffs[0]), float(lin_coeffs[1])
    c1, c2 = center_guess_1, center_guess_2
    linear_at_c1 = slope0 * c1 + intercept0
    linear_at_c2 = slope0 * c2 + intercept0
    amp01 = float(np.interp(c1, wl, fl)) - linear_at_c1
    amp02 = float(np.interp(c2, wl, fl)) - linear_at_c2

    if line_type == "absorption":
        amp01 = min(amp01, -1e-6); amp02 = min(amp02, -1e-6)
        amp_lo, amp_hi = -np.inf, 0.0
    else:
        amp01 = max(amp01, 1e-6); amp02 = max(amp02, 1e-6)
        amp_lo, amp_hi = 0.0, np.inf

    sigma0 = np.clip(width_3sigma / 3.0, 2.0, half / 4.0)
    p0 = [amp01, c1, sigma0, amp02, c2, sigma0, slope0, intercept0]
    bounds = (
        [amp_lo, c1 - 50, 1.0, amp_lo, c2 - 50, 1.0, -np.inf, -np.inf],
        [amp_hi, c1 + 50, half, amp_hi, c2 + 50, half, np.inf, np.inf],
    )

    try:
        popt, pcov = curve_fit(_doublet_model, wl, fl, p0=p0, bounds=bounds, maxfev=10000)
    except Exception as e:
        c1_r = _try_fit_single(wl, fl, c1, width_3sigma, line_type, window_half)
        c2_r = _try_fit_single(wl, fl, c2, width_3sigma, line_type, window_half)
        flags = ["doublet_fit_failed"]
        msg = f"Doublet fit failed: {e}. "
        if c1_r and c2_r:
            flags.append("fallback_individual")
            msg += "Fell back to individual fits."
        else:
            msg += "Individual fits also failed."
        return _build_doublet_result(None, None, len(wl), flags, msg, c1_r, c2_r)

    amp1, c1_f, s1, amp2, c2_f, s2, slope, intercept = popt

    def _cs(amp, c, s):
        fwhm = s * 2.35482
        return {
            "center": round(float(c), 3),
            "amplitude": round(float(amp), 6),
            "sigma": round(float(s), 3),
            "fwhm": round(float(fwhm), 3),
            "fwhm_km_s": round(float(fwhm / c * 2.99792458e5), 1) if c != 0 else None,
        }

    c1_info = _cs(amp1, c1_f, s1)
    c2_info = _cs(amp2, c2_f, s2)

    fitted = _doublet_model(wl, *popt)
    linear_only = slope * wl + intercept
    residuals = fl - fitted
    local_rms = 1.4826 * np.median(np.abs(residuals - np.median(residuals)))
    if local_rms < 1e-10:
        local_rms = float(np.std(residuals)) or 1e-10

    n = len(wl)
    chi2_full = np.sum((residuals / local_rms) ** 2)
    chi2_linear = np.sum(((fl - linear_only) / local_rms) ** 2)
    delta_chi2_per_n = round(float((chi2_linear - chi2_full) / n), 3)
    max_amp = max(abs(amp1), abs(amp2))
    local_snr = round(float(max_amp / local_rms), 2)

    sep_check = None
    if separation_rest is not None:
        obs_sep = abs(c1_info["center"] - c2_info["center"])
        sep_check = {
            "observed_sep_A": round(obs_sep, 2),
            "expected_sep_A": round(float(separation_rest), 2),
            "match": obs_sep <= separation_rest + separation_tolerance,
        }

    amp_check = None
    if amp_ratio_expected is not None and abs(c1_info["amplitude"]) > 1e-10:
        obs_ratio = abs(c2_info["amplitude"]) / abs(c1_info["amplitude"])
        amp_check = {
            "observed_ratio": round(obs_ratio, 2),
            "expected_ratio": round(float(amp_ratio_expected), 2),
        }

    flags = []
    for i, ci, cg in [(1, c1_info, center_guess_1), (2, c2_info, center_guess_2)]:
        if abs(ci["center"] - cg) > 50:
            flags.append(f"center_{i}_deviation_large")
    if delta_chi2_per_n < 0:
        flags.append("negative_delta_chi2")

    msg = f"Fit {'OK' if not flags else 'warnings'}. "
    msg += f"C1: {c1_info['center']:.2f}Å amp={c1_info['amplitude']:.4f} FWHM={c1_info['fwhm']:.1f}Å. "
    msg += f"C2: {c2_info['center']:.2f}Å amp={c2_info['amplitude']:.4f} FWHM={c2_info['fwhm']:.1f}Å. "
    msg += f"S/N={local_snr:.1f} Δχ²/n={delta_chi2_per_n:.1f}"
    if sep_check:
        msg += f" sep={sep_check['observed_sep_A']:.1f}Å {'✓' if sep_check['match'] else '✗'}"

    return {
        "component_1": c1_info,
        "component_2": c2_info,
        "delta_chi2_per_n": delta_chi2_per_n,
        "local_rms": round(float(local_rms), 6),
        "local_snr": local_snr,
        "separation_check": sep_check,
        "amp_ratio_check": amp_check,
        "n_points": n,
        "flags": flags,
        "message": msg,
    }


def _try_fit_single(wl, fl, center_guess, width_3sigma, line_type, window_half):
    """Attempt single-Gaussian fit on a sub-array. Returns dict or None."""
    half = min(window_half, 200.0)
    mask = (wl >= center_guess - half) & (wl <= center_guess + half)
    w, f = wl[mask], fl[mask]; g = np.isfinite(f); w, f = w[g], f[g]
    if len(w) < 10:
        return None
    lin = np.polyfit(w, f, 1)
    s0, i0 = float(lin[0]), float(lin[1])
    a0 = float(np.interp(center_guess, w, f)) - (s0 * center_guess + i0)
    if line_type == "absorption":
        a0 = min(a0, -1e-6); lo, hi = -np.inf, 0.0
    else:
        a0 = max(a0, 1e-6); lo, hi = 0.0, np.inf
    sig0 = np.clip(width_3sigma / 3.0, 2.0, half / 2)
    try:
        popt, _ = curve_fit(
            _gaussian_plus_linear, w, f,
            p0=[a0, center_guess, sig0, s0, i0],
            bounds=([lo, center_guess - 50, 1.0, -np.inf, -np.inf],
                    [hi, center_guess + 50, half, np.inf, np.inf]),
            maxfev=5000,
        )
        amp, c, s, _, _ = popt
        fwhm = s * 2.35482
        return {
            "center": round(float(c), 3),
            "amplitude": round(float(amp), 6),
            "sigma": round(float(s), 3),
            "fwhm": round(float(fwhm), 3),
            "fwhm_km_s": round(float(fwhm / c * 2.99792458e5), 1) if c != 0 else None,
        }
    except Exception:
        return None


def _build_doublet_result(c1_info, c2_info, n_pts, flags, msg, fb1=None, fb2=None):
    return {
        "component_1": c1_info or fb1,
        "component_2": c2_info or fb2,
        "delta_chi2_per_n": None, "local_rms": None, "local_snr": None,
        "separation_check": None, "amp_ratio_check": None,
        "n_points": n_pts, "flags": flags, "message": msg,
    }
