"""Single-Hypothesis prompt builder.

Builds the user prompt (CWT features table + predicted lines at a given z)
for the SH LangChain agent.  The LLM calls fit_peak/fit_doublet tools to
verify each predicted line.

Adapted from FORMA ``harness/single_hypothesis.py``.
"""

import numpy as np

from cataloga.tools.lines import predict_lines, WIDTH_3SIGMA
from cataloga.tools.spectrum import load_coadd_spectrum, merged_spectrum

# ---------------------------------------------------------------------------
# Arm masking
# ---------------------------------------------------------------------------

# DESI arm ranges (B / R / Z); overlap zones are R/Z boundary near 7520–7620
ARM_RANGES = {"B": (3600, 5800), "R": (5760, 7620), "Z": (7520, 9824)}


def _masked_regions():
    """Return overlap zones that should be masked or treated with caution."""
    return [(7620, 7520)]  # R/Z gap (R ends at 7620, Z starts at 7520 — no gap actually...)


def _mask_overlap_label(lo: float, hi: float, obs_wl: float,
                        masked: list | None) -> str:
    if not masked:
        return ""
    for m_lo, m_hi in masked:
        lo_in = m_lo <= lo <= m_hi
        hi_in = m_lo <= hi <= m_hi
        obs_in = m_lo <= obs_wl <= m_hi
        any_in = lo <= m_hi and hi >= m_lo
        if not any_in:
            continue
        if lo_in and hi_in:
            return " [fully masked]"
        if obs_in:
            return " [λ_pred masked]"
        return " [window partially masked]"
    return ""


# ---------------------------------------------------------------------------
# Feature lookup
# ---------------------------------------------------------------------------

def _find_nearby_features(rest_wl: float, obs_wl: float,
                          z_min: float, z_max: float,
                          features: list) -> str:
    """Return nearby CWT features in the z-verification window."""
    lo = rest_wl * (1.0 + z_min)
    hi = rest_wl * (1.0 + z_max)
    nearby = []
    for f in (features or []):
        fw = f.get("wavelength", 0)
        if lo <= fw <= hi:
            z_implied = fw / rest_wl - 1.0
            wl_err = f.get("wavelength_err")
            err_str = f"±{wl_err:.1f}" if isinstance(wl_err, (int, float)) else ""
            ftype_short = "em" if f["feature_type"].startswith("em") else "abs"
            nearby.append((abs(fw - obs_wl),
                          f"{ftype_short}@{fw:.1f}{err_str}(z={z_implied:.4f})"))
    nearby.sort(key=lambda x: x[0])
    return ", ".join(n[1] for n in nearby) if nearby else "—"


def _build_cwt_features_table(peaks: list, troughs: list) -> str:
    """Build a Markdown table of all CWT-detected features."""
    lines = ["## CWT Detected Features\n"]
    col = "| λ (Å) | λ_err (Å) | Amp | FWHM (Å) | FWHM (km/s) | Ridge | SNR |"
    sep = "|-------|-----------|-----|----------|-------------|-------|-----|"

    def _row(f: dict) -> str:
        wl = f.get("wavelength", 0)
        wl_err = f.get("wavelength_err", "—")
        amp = f.get("amplitude", 0)
        fwhm_a = f.get("FWHM_A", "—")
        fwhm_k = f.get("FWHM_km_s", "—")
        ridge = f.get("ridge_length", "—")
        snr = f.get("snr", "—")
        return (f"| {float(wl):.1f} | {wl_err if wl_err != '—' else '—'} | "
                f"{float(amp):.1f} | "
                f"{float(fwhm_a):.1f}" if isinstance(fwhm_a, (int, float)) else f"{fwhm_a} | "
                f"{float(fwhm_k):.0f}" if isinstance(fwhm_k, (int, float)) else f"{fwhm_k} | "
                f"{ridge if isinstance(ridge, (int, float)) and False else str(ridge)} | "
                f"{float(snr):.1f}" if isinstance(snr, (int, float)) else f"{snr} |")

    # Simplified _row:
    def _row2(f: dict) -> str:
        vals = []
        for k in ["wavelength", "wavelength_err", "amplitude", "FWHM_A", "FWHM_km_s",
                   "ridge_length", "snr"]:
            v = f.get(k, "—")
            if isinstance(v, float):
                if k in ("wavelength", "wavelength_err", "FWHM_A"):
                    vals.append(f"{v:.1f}")
                elif k == "FWHM_km_s":
                    vals.append(f"{v:.0f}")
                elif k == "amplitude":
                    vals.append(f"{v:.1f}")
                elif k == "snr":
                    vals.append(f"{v:.1f}")
                else:
                    vals.append(str(v))
            else:
                vals.append(str(v) if v is not None else "—")
        return "| " + " | ".join(vals) + " |"

    if peaks:
        lines.append(f"### Emission (peaks) — {len(peaks)} features\n")
        lines.append(col); lines.append(sep)
        for p in peaks:
            lines.append(_row2(p))
        lines.append("")
    if troughs:
        lines.append(f"### Absorption (troughs) — {len(troughs)} features\n")
        lines.append(col); lines.append(sep)
        for t in troughs:
            lines.append(_row2(t))
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Predicted lines section
# ---------------------------------------------------------------------------

def _make_fit_cell(fit_result: dict) -> str:
    """Build a compact fit result string for the table."""
    if fit_result is None or fit_result.get("center") is None:
        return "—"
    c = fit_result.get("center", 0)
    ce = fit_result.get("center_err")
    snr = fit_result.get("local_snr", 0)
    fwhm = fit_result.get("fwhm_km_s")
    dchi = fit_result.get("delta_chi2_per_n", 0)
    parts = [f"c={c:.1f}"]
    if ce is not None:
        parts.append(f"±{ce:.1f}")
    parts.append(f"S/N={snr:.1f}")
    if fwhm is not None:
        parts.append(f"FWHM={fwhm:.0f}km/s")
    parts.append(f"Δχ²/n={dchi:.1f}")
    return " ".join(parts)


def _build_predictions_section(redshift: float, z_min: float, z_max: float,
                               wl_min: float, wl_max: float,
                               peaks: list, troughs: list,
                               masked_regions: list | None = None,
                               fit_results: dict | None = None) -> str:
    """Pre-compute predicted lines, cross-reference with CWT features AND
    pre-computed fit_peak results."""

    pred = predict_lines(redshift, line_type="all",
                         wavelength_min=wl_min, wavelength_max=wl_max)
    rows = []
    for line in pred["lines"]:
        obs_wl = line["obs_wl"]
        rest_wl = line["rest_wl"]
        lo = rest_wl * (1.0 + z_min)
        hi = rest_wl * (1.0 + z_max)
        ft_f = peaks if line["type"] == "emission" else troughs
        features = _find_nearby_features(rest_wl, obs_wl, z_min, z_max, ft_f)
        mask_note = _mask_overlap_label(lo, hi, obs_wl, masked_regions)
        wclass = line["width_class"]
        # Look up pre-computed fit result
        fit_cell = "—"
        if fit_results and line["name"] in fit_results:
            fit_cell = _make_fit_cell(fit_results[line["name"]])
        rows.append((obs_wl,
            f"| {line['name']} | {rest_wl:.1f} | {obs_wl:.1f} | "
            f"{'em' if line['type'] == 'emission' else 'abs'} | "
            f"{wclass} | {features}{mask_note} | {fit_cell} |"))

    if not rows:
        return "\n## Predicted Lines\n\n(No predicted lines fall in range.)\n"

    rows.sort(key=lambda r: r[0])
    header = (
        "| Name | λ_rest (Å) | λ_obs (Å) | Type | Width | Nearby CWT Features | "
        "fit_peak Result (center, S/N, FWHM, Δχ²/n) |\n"
        "|------|-----------|----------|------|-------|---------------------|"
        "-----------------------------------------------------|"
    )
    lines_str = (
        f"\n## Predicted Lines at z = {redshift:.4f}\n\n"
        f"**How to use**: The CWT Features column lists pre-detected wavelet features "
        f"in the z-verification window [z={z_min:.4f}, z={z_max:.4f}] (ref@λ with implied_z). "
        f"If CWT features are present, evaluate them FIRST (higher trust).\n"
        f"The **fit_peak Result** column shows a pre-computed Gaussian+linear fit at λ_obs "
        f"using the appropriate width_3sigma for this line class. Use this to CONFIRM or "
        f"REFUTE CWT findings, especially for BROAD lines (Lyα, C IV, C III], Mg II) which "
        f"CWT may miss because they are wider than the wavelet scales.\n\n"
        f"**Lyα special note**: Lyα at z≳1.5 is highly asymmetric (blue-absorbed wing + "
        f"red emission peak). A single Gaussian will systematically underpredict S/N and "
        f"overpredict FWHM. If fit_peak finds ANY emission (S/N≥2, Δχ²/n≥1), treat as "
        f"positive evidence even if offset is large — do NOT reject Lyα on center offset alone.\n"
        f"When evaluating broad lines, the fit_peak S/N is a LOWER BOUND — the true line "
        f"flux is larger than a single Gaussian can capture.\n\n"
        f"{header}\n"
    )
    return lines_str + "\n".join(r[1] for r in rows) + "\n"


# ---------------------------------------------------------------------------
# Full user message builder
# ---------------------------------------------------------------------------

def build_user_message(
    redshift: float,
    coadd_path: str,
    targetid: int,
    peaks: list,
    troughs: list,
    fit_results: dict = None,
    report_path: str = None,
    csv_path: str = None,
    z_min: float = None,
    z_max: float = None,
    snr_median: float = None,
    masked_regions: list = None,
) -> str:
    """Build the complete user prompt for the SH agent.

    Parameters
    ----------
    redshift : float
        The redshift hypothesis to evaluate.
    coadd_path : str
        Path to the coadd FITS file (for context).
    targetid : int
    peaks, troughs : list[dict]
        CWT-detected features from ``find_features_cwt()``.
    report_path, csv_path : str, optional
        Output paths for write_report / write_lines_csv.
    z_min, z_max : float, optional
        Verification window. Defaults to redshift ± 0.1.
    snr_median : float, optional
        Pre-computed median SNR.
    masked_regions : list of (float, float), optional
        Wavelength ranges to mask.

    Returns
    -------
    str — the user message to send to the LLM.
    """
    _z_min = z_min if z_min is not None else round(redshift - 0.1, 4)
    _z_max = z_max if z_max is not None else round(redshift + 0.1, 4)
    _masked = masked_regions or []

    # Load spectrum for summary
    sp = load_coadd_spectrum(coadd_path, targetid)
    w_all, f_all, iv_all = merged_spectrum(sp)
    wl_min, wl_max = float(np.nanmin(w_all)), float(np.nanmax(w_all))

    import numpy as _np
    if snr_median is None:
        noise = 1.0 / _np.sqrt(_np.maximum(iv_all, 1e-30))
        # Use per-pixel noise from IVAR where available, fall back to robust std
        valid = _np.isfinite(noise) & (noise < 1e10)
        if valid.sum() > 100:
            snr_arr = _np.abs(f_all) / noise
            snr_median_val = float(_np.nanmedian(snr_arr[valid]))
        else:
            snr_arr = _np.abs(f_all) / (1.4826 * _np.nanmedian(_np.abs(f_all - _np.nanmedian(f_all))))
            snr_median_val = float(_np.nanmedian(snr_arr))
    else:
        snr_median_val = snr_median

    # Spectrum summary
    spec_lines = [f"| Wavelength range | {wl_min:.1f} – {wl_max:.1f} Å |",
                  f"| Median SNR | {snr_median_val:.1f} |"]
    _masked_msg = ""
    if _masked:
        regions_desc = ", ".join(f"[{s:.1f}, {e:.1f}]" for s, e in _masked)
        spec_lines.append(f"| Masked regions | {regions_desc} |")
        _masked_msg = (
            "\nThese regions were removed due to arm overlap or quality cuts. "
            "The spectrum has NO data in these ranges. "
            "In the Predicted Lines table, mask overlap is noted in [brackets]:\n"
            "  - ``[fully masked]`` — entire z-window has no data → MASKED\n"
            "  - ``[λ_pred masked]`` — nominal position masked → evaluate normally\n"
            "  - ``[window partially masked]`` — part of window masked → flag as caution\n"
        )

    spectrum_summary = "## Spectrum Summary\n\n" + "\n".join(spec_lines) + "\n"

    predictions_section = _build_predictions_section(
        redshift, _z_min, _z_max, wl_min, wl_max, peaks, troughs, _masked,
        fit_results=fit_results)
    cwt_table = _build_cwt_features_table(peaks, troughs)

    n_fits = len(fit_results) if fit_results else 0
    mode_instructions = ""
    if n_fits > 0:
        mode_instructions = (
            "\n## Pre-Computed fit_peak Results\n\n"
            f"The Predicted Lines table includes **pre-computed Gaussian+linear fits** "
            f"for all {n_fits} lines. These are computed with the appropriate width_3sigma "
            f"for each line class (broad=90Å, narrow=25Å, both=50Å).\n\n"
            "**Evaluation workflow**:\n"
            "1. Check the **CWT Features** column first — pre-detected wavelet features "
            "are higher-trust than single-Gaussian fits\n"
            "2. Use the **fit_peak Result** column to CONFIRM or REFUTE:\n"
            "   - **S/N ≥ 3 AND Δχ²/n ≥ 1** → positive evidence (confirming)\n"
            "   - **S/N ≥ 1.5** → marginal evidence (may be real but weak)\n"
            "   - **S/N < 1.5** → no detection\n"
            "3. For **broad lines** (Lyα, C IV, C III], Mg II): S/N is a LOWER BOUND.\n"
        "4. For **Lyα specifically**: asymmetric profile (blue absorption + red emission). "
        "Single Gaussian fit will underestimate S/N and overestimate FWHM. "
        "**If Lyα fit shows S/N ≥ 2 and Δχ²/n ≥ 1, assign at least MARGINAL** — "
        "do NOT reject on center offset alone (offsets ≤ 100 Å are expected for "
        "asymmetric Lyα at this SNR).\n\n"
    )

    return (
        spectrum_summary
        + f"\nVerify the redshift hypothesis z ≈ {redshift}.\n\n"
        f"Verification window: z ∈ [{_z_min}, {_z_max}]\n"
        f"A CWT feature supports the hypothesis ONLY if its implied_z falls within "
        f"this window. Each feature in the table already has its z pre-computed.\n"
        f"Lines marked [fully masked] have NO data → assign MASKED.\n"
        + _masked_msg
        + mode_instructions
        + f"\nFITS file: {coadd_path}\n"
        + f"TARGETID: {targetid}\n"
        + (f"Output Report file: {report_path}\n" if report_path else "")
        + (f"Output CSV file: {csv_path}\n" if csv_path else "")
        + "\n" + cwt_table + "\n"
        + predictions_section
        + "\nThe CWT table lists all pre-detected features with their quality metrics. "
        "The Predicted Lines table references nearby features by wavelength + implied_z — "
        "cross-reference with the CWT table for FWHM, ridge, and SNR details. "
        "Evaluate and adopt features per the skill prompt criteria.\n"
        + "\nBatch ALL line decisions in a single parallel turn.\n"
        + "\nPhases: evaluate all lines → write CSV → write report → JSON block."
    )
