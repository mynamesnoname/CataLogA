"""CWT feature detection using Ricker (Mexican hat) wavelet.

Pure numpy/scipy implementation — no PyWavelets dependency.
The Ricker wavelet (second derivative of Gaussian) is a natural matched
filter for Gaussian-like spectral lines.

Algorithm (same as FORMA's ``cwt_feature_finder.py``):
1. Median-filter continuum subtraction → residual
2. Ricker CWT across log-spaced scales (1–80 px)
3. Ridge detection: link local maxima/minima across adjacent scales
4. MAD noise estimation + SNR thresholding
5. Classify as emission (positive ridge) or absorption (negative ridge)
"""

import numpy as np
from scipy.signal import find_peaks

SIGMA_TO_FWHM = 2.0 * np.sqrt(2.0 * np.log(2.0))


# ---------------------------------------------------------------------------
# Local noise estimation
# ---------------------------------------------------------------------------

def _local_noise_mad(signal, half_window=50):
    """Sliding-window MAD noise estimate, robust against line features."""
    n = len(signal)
    noise = np.zeros(n, dtype=np.float64)
    for i in range(n):
        lo = max(0, i - half_window)
        hi = min(n, i + half_window + 1)
        chunk = signal[lo:hi]
        noise[i] = 1.4826 * np.median(np.abs(chunk - np.median(chunk)))
    return np.maximum(noise, np.median(noise) * 0.1)


# ---------------------------------------------------------------------------
# Ricker wavelet CWT
# ---------------------------------------------------------------------------

def _ricker_wavelet(width):
    """Ricker (Mexican hat) wavelet of given width in pixels.

    Returns (t, ψ) where t is centred at 0 and ∫ψ dt ≈ 0.
    """
    t = np.arange(-4 * width, 4 * width + 1, dtype=np.float64)
    a = 2.0 / (np.sqrt(3 * width) * np.pi**0.25)
    x = t / width
    psi = a * (1 - x**2) * np.exp(-x**2 / 2)
    return t, psi


def _cwt_ricker(signal, scales):
    """Compute Ricker CWT at each scale via convolution.

    Returns (n_scales, n_pixels) coefficient matrix.
    """
    n = len(signal)
    n_scales = len(scales)
    coef = np.zeros((n_scales, n), dtype=np.float64)
    for i, s in enumerate(scales):
        if s < 1.0:
            s = 1.0
        t, psi = _ricker_wavelet(s)
        conv = np.convolve(signal, psi, mode='same')
        coef[i, :] = conv / max(np.sum(np.abs(psi)), 1e-10)
    return coef


# ---------------------------------------------------------------------------
# Ridge detection
# ---------------------------------------------------------------------------

def _cwt_ridge_detection(signal, wavelength, scales, snr_thresh=5.0,
                         min_ridge_length=2, tol_pix=10):
    """Multi-scale ridge detection in CWT coefficient space.

    Finds local maxima that persist across adjacent wavelet scales.

    Returns list of dict with: wavelength, amplitude, fwhm_pix, ridge_length, snr.
    """
    n = len(signal)
    if n < 10:
        return []

    noise = _local_noise_mad(signal)
    cwt_mat = _cwt_ricker(signal, scales)

    detections = []  # (pixel_idx, scale_idx, cwt_value, snr)
    for i in range(len(scales)):
        row = cwt_mat[i, :]
        peaks_idx, _ = find_peaks(row, width=1)
        for pi in peaks_idx:
            local_snr = float(row[pi]) / noise[pi] if noise[pi] > 0 else 0.0
            if local_snr >= snr_thresh:
                detections.append((int(pi), i, float(row[pi]), local_snr))

    if not detections:
        return []

    detections.sort(key=lambda x: (x[1], x[0]))  # by (scale, pixel)

    ridges = []  # list of lists
    for det in detections:
        pi, si, val, snr = det
        matched = False
        for ridge in ridges:
            last_pi, last_si, _, _ = ridge[-1]
            if last_si == si - 1 and abs(pi - last_pi) <= tol_pix:
                ridge.append(det)
                matched = True
                break
            if last_si == si and abs(pi - last_pi) <= tol_pix:
                if snr > ridge[-1][3]:
                    ridge[-1] = det
                matched = True
                break
        if not matched:
            ridges.append([det])

    results = []
    mean_dwave = float(np.median(np.diff(wavelength))) if len(wavelength) > 1 else 1.0

    for ridge in ridges:
        if len(ridge) < min_ridge_length:
            continue
        pixels = [d[0] for d in ridge]
        scales_detected = [scales[d[1]] for d in ridge]
        rep_idx = int(np.median(pixels))
        rep_wave = float(wavelength[rep_idx])
        rep_amp = float(signal[rep_idx])
        med_scale = float(np.median(scales_detected))
        fwhm_pix = max(med_scale * SIGMA_TO_FWHM, 2.0)
        max_snr = max(d[3] for d in ridge)
        results.append({
            "wavelength": rep_wave,
            "amplitude": rep_amp,
            "fwhm_pix": fwhm_pix,
            "ridge_length": len(ridge),
            "snr": max_snr,
        })
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_features_cwt(wavelength, flux, snr_thresh=5.0, min_ridge_length=2,
                      n_scales=24, min_scale=1.0, max_scale=80.0,
                      verbose=True):
    """CWT-based emission and absorption line detection.

    Parameters
    ----------
    wavelength, flux : 1-D arrays
    snr_thresh : float
        Minimum CWT SNR to keep a detection.
    min_ridge_length : int
        Minimum number of scales for a valid ridge (≥ 2).
    n_scales : int
        Number of log-spaced wavelet scales.
    min_scale, max_scale : float
        Scale range in pixel units.
    verbose : bool

    Returns
    -------
    records_emission, records_absorption : list[dict]
    """
    n = len(flux)
    if n < 10:
        return [], []

    # Interpolate NaN pixels so they don't contaminate convolution output
    good = np.isfinite(flux)
    if not np.all(good):
        interp = np.interp(np.arange(len(flux)), np.where(good)[0], flux[good])
    else:
        interp = flux

    # Chebyshev continuum fitting (ported from FORMA VI.py) → residual
    from cataloga.tools.continuum import run_continuum_fitting_masked
    _continuum, residual = run_continuum_fitting_masked(
        wavelength, interp, peaks=None, troughs=None,
        chebyshev_min_degree=1, chebyshev_max_degree=10, verbose=False,
    )

    scales = np.logspace(np.log10(min_scale), np.log10(max_scale), n_scales)
    mean_dwave = np.median(np.diff(wavelength)) if len(wavelength) > 1 else 1.0

    # Emission: positive features in residual
    em_candidates = _cwt_ridge_detection(
        residual, wavelength, scales, snr_thresh=snr_thresh,
        min_ridge_length=min_ridge_length)

    # Absorption: positive features in -residual (troughs → peaks)
    ab_candidates = _cwt_ridge_detection(
        -residual, wavelength, scales, snr_thresh=snr_thresh,
        min_ridge_length=min_ridge_length)

    def _records(candidates, ftype):
        recs = []
        for c in candidates:
            amp = c["amplitude"]
            if ftype == "absorption":
                amp = -abs(amp)
            fwhm_a = c["fwhm_pix"] * mean_dwave
            fwhm_km_s = fwhm_a / c["wavelength"] * 3e5 if c["wavelength"] > 0 else 0
            recs.append({
                "wavelength": c["wavelength"],
                "wavelength_err": float(mean_dwave),
                "FWHM_A": float(fwhm_a),
                "FWHM_km_s": float(fwhm_km_s),
                "amplitude": float(amp),
                "width_class": (
                    "narrow" if fwhm_km_s < 1000 else
                    "intermediate" if fwhm_km_s < 2000 else "broad"
                ),
                "feature_type": ftype,
                "ridge_length": c["ridge_length"],
                "snr": c["snr"],
            })
        return recs

    records_em = _records(em_candidates, "emission")
    records_ab = _records(ab_candidates, "absorption")

    if verbose:
        rl_em = {}
        for r in records_em:
            rl_em[r["ridge_length"]] = rl_em.get(r["ridge_length"], 0) + 1
        rl_ab = {}
        for r in records_ab:
            rl_ab[r["ridge_length"]] = rl_ab.get(r["ridge_length"], 0) + 1
        print(f"[cwt] scales={n_scales}×[{min_scale:.0f}..{max_scale:.0f}]px "
              f"SNR≥{snr_thresh}: {len(records_em)} peaks{rl_em}, "
              f"{len(records_ab)} troughs{rl_ab}")

    return records_em, records_ab
