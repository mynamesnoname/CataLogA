"""[O II] 3727 unresolved-doublet slope-change detector.

Ported from FORMA's ``harness/tools.py:detect_oii_slope_change()``.

[O II] 3727 is a close doublet (3726.0/3729.0 Å, rest sep 2.8 Å) that is
unresolved at DESI resolution (R ≈ 2000–5000).  Although it appears as a
single peak, the rising edge of the profile carries a characteristic signature:
the discrete derivative shows a **dip** — the rise rate peaks, drops
significantly, then recovers before the flux peaks.  A true single line
cannot produce this pattern.

Two detection modes:

- **valley** (dip_deriv < 0) — unambiguous: flux briefly *reverses* on the
  rising edge (the inter-component gap).  Strongest [O II] evidence.
- **slope-change** (dip_ratio = min_deriv / max_deriv < dip_threshold) —
  the derivative dips to a small positive value, then recovers.  Consistent
  with [O II] when the SNR is insufficient for a full flux reversal.

Use this to discriminate [O II] from [O III]b when the SAME observed feature
is claimed by competing hypotheses.
"""

import numpy as np


def detect_oii_slope_change(
    wavelength,
    flux,
    target_wl: float,
    search_window: float = 25.0,
    rise_search_n: int = 20,
    dip_threshold: float = 0.20,
    recovery_threshold: float = 2.0,
) -> dict:
    """Detect the [O II] unresolved-doublet slope-change signature.

    Parameters
    ----------
    wavelength, flux : 1-D arrays
    target_wl : float
        Observed wavelength (Å) where [O II] is claimed.
    search_window : float
        Half-width of search window around target_wl (default 25 Å).
    rise_search_n : int
        Pixels to search blueward of the peak for the rising edge.
    dip_threshold : float
        dip_deriv / max_deriv < dip_threshold → slope-change detected.
    recovery_threshold : float
        recovery_deriv / dip_deriv > recovery_threshold → recovery confirmed.

    Returns
    -------
    dict with detected, signature_type, peak_wl, peak_flux, dip_ratio,
         max_deriv, dip_deriv, recovery_deriv, fwhm_A, fwhm_km_s, …
    """
    mask = (wavelength >= target_wl - search_window) & (wavelength <= target_wl + search_window)
    w = wavelength[mask]; f = flux[mask]
    good = np.isfinite(f)
    w, f = w[good], f[good]

    nop = lambda: dict(detected=False, reason="")
    if len(w) < 10:
        r = nop(); r["reason"] = f"Too few points ({len(w)})"; return r

    peak_idx = int(np.argmax(f))
    peak_wl = float(w[peak_idx])
    peak_flux = float(f[peak_idx])

    # Extract rising edge: ~5 to rise_search_n pixels blueward of peak
    rise_start = max(0, peak_idx - rise_search_n)
    rise_end = peak_idx
    rise_f = f[rise_start:rise_end + 1]
    rise_w = w[rise_start:rise_end + 1]

    if len(rise_f) < 6:
        r = nop(); r["reason"] = f"Rising edge too short ({len(rise_f)} px)"
        r["peak_wl"], r["peak_flux"] = peak_wl, peak_flux; return r

    # Discrete derivative (exclude last 2 pixels → avoid peak curvature)
    deriv = np.diff(rise_f)[:-2]
    deriv_wl = rise_w[1:len(deriv) + 1]

    if len(deriv) < 5:
        r = nop(); r["reason"] = f"Derivative too short ({len(deriv)} px)"
        r["peak_wl"], r["peak_flux"] = peak_wl, peak_flux; return r

    max_deriv_idx = int(np.argmax(deriv))
    max_deriv = float(deriv[max_deriv_idx])
    max_deriv_wl = float(deriv_wl[max_deriv_idx])

    post_peak = deriv[max_deriv_idx + 1:]
    if len(post_peak) < 2:
        r = nop(); r["reason"] = "Insufficient pixels after max deriv"
        r["peak_wl"] = peak_wl; r["peak_flux"] = peak_flux
        r["max_deriv"] = max_deriv; r["max_deriv_wl"] = max_deriv_wl
        return r

    dip_idx = max_deriv_idx + 1 + int(np.argmin(post_peak))
    dip_deriv = float(deriv[dip_idx])
    dip_wl = float(deriv_wl[dip_idx])

    post_dip = deriv[dip_idx + 1:]
    recovery_deriv = float(np.max(post_dip)) if len(post_dip) > 0 else 0.0
    if len(post_dip) > 0:
        recovery_idx = dip_idx + 1 + int(np.argmax(post_dip))
        recovery_wl = float(deriv_wl[recovery_idx])
    else:
        recovery_wl = None

    dip_ratio = dip_deriv / max_deriv if max_deriv > 1e-10 else 1.0

    if dip_deriv < 0 and max_deriv > 1e-10:
        detected = True; signature_type = "valley"; recovery_ok = True
    else:
        signature_type = "slope-change"
        if len(post_dip) >= 2:
            recovery_ok = recovery_deriv > dip_deriv * recovery_threshold if dip_deriv > 0 else False
            detected = dip_ratio < dip_threshold and recovery_ok
        else:
            recovery_ok = None
            detected = dip_ratio < dip_threshold

    # FWHM estimate
    fwhm_A, fwhm_km_s = None, None
    if peak_flux > 0:
        pre_rise = f[:rise_start + 1]
        continuum = float(np.min(pre_rise)) if len(pre_rise) > 0 else float(f[0])
        half_max = continuum + (peak_flux - continuum) / 2.0
        left_wl = right_wl = None
        for i in range(peak_idx - 1, 0, -1):
            if w[i] != w[i+1] and f[i] <= half_max <= f[i + 1]:
                frac = (half_max - f[i]) / max(f[i + 1] - f[i], 1e-30)
                left_wl = w[i] + (w[i + 1] - w[i]) * frac
                break
        for i in range(peak_idx, len(f) - 1):
            if w[i] != w[i+1] and f[i] >= half_max >= f[i + 1]:
                frac = (f[i] - half_max) / max(f[i] - f[i + 1], 1e-30)
                right_wl = w[i] + (w[i + 1] - w[i]) * frac
                break
        if left_wl is not None and right_wl is not None:
            fwhm_A = round(float(right_wl - left_wl), 2)
            fwhm_km_s = round(float(fwhm_A / peak_wl * 2.99792458e5), 0)

    return {
        "detected": detected,
        "signature_type": signature_type if detected else None,
        "peak_wl": peak_wl,
        "peak_flux": round(peak_flux, 4),
        "dip_ratio": round(dip_ratio, 3),
        "dip_threshold": dip_threshold,
        "max_deriv": round(max_deriv, 6),
        "max_deriv_wl": max_deriv_wl,
        "dip_deriv": round(dip_deriv, 6),
        "dip_wl": dip_wl,
        "recovery_deriv": round(recovery_deriv, 6),
        "recovery_wl": recovery_wl,
        "recovery_ok": recovery_ok,
        "fwhm_A": fwhm_A,
        "fwhm_km_s": fwhm_km_s,
        "deriv_profile": [round(float(d), 6) for d in deriv],
        "deriv_wl": [round(float(dw), 1) for dw in deriv_wl],
        "n_rise_pixels": len(rise_f),
        "n_deriv_points": len(deriv),
        "n_post_dip": len(post_dip),
    }
