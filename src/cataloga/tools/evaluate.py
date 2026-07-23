"""Hypothesis evaluator — the core agent logic.

Given a TARGETID and a redshift hypothesis, systematically checks whether
the predicted spectral lines are actually present in the spectrum.

This is the CataLogA equivalent of FORMA's Single-Hypothesis Evaluation agent
(HypothesisAnalyst → single_hypothesis.py).

Core loop::

    predict_lines(z) → for each predicted line in spectral range:
        fit_peak() or fit_doublet()  →  status: LIKELY / MARGINAL / NOT_FOUND

Returns a structured report with per-line evaluation and an overall score.
"""

import os
import numpy as np

from cataloga.tools.lines import predict_lines, DOUBLET_PARAMS, WIDTH_3SIGMA
from cataloga.tools.spectrum import load_coadd_spectrum, merged_spectrum
from cataloga.tools.fitting import fit_peak, fit_doublet

C_KMS = 299792.458

# Status thresholds
LOCAL_SNR_LIKELY = 5.0   # local_snr >= this → LIKELY
LOCAL_SNR_MARGINAL = 2.0  # local_snr >= this → MARGINAL; below → NOT_FOUND
CENTER_DEV_TOL = 50.0     # Å — |fitted_center - predicted| > this → downgrade


def evaluate_hypothesis(
    coadd_path: str,
    targetid: int,
    redshift: float,
    line_type: str = "all",
    verbose: bool = True,
) -> dict:
    """Evaluate how well predicted lines at *z* match the observed spectrum.

    Parameters
    ----------
    coadd_path : str
        Path to the DESI coadd FITS file.
    targetid : int
    redshift : float
        The redshift hypothesis to test.
    line_type : "emission", "absorption", or "all"
    verbose : bool

    Returns
    -------
    dict with keys:
        redshift, n_predicted, n_likely, n_marginal, n_not_found,
        score (fraction of predicted lines detected), lines (per-line reports).
    """
    spectrum = load_coadd_spectrum(coadd_path, targetid)
    w_all, f_all, _ = merged_spectrum(spectrum)
    wl_min, wl_max = float(w_all[0]), float(w_all[-1])

    pred = predict_lines(redshift, line_type=line_type,
                         wavelength_min=wl_min, wavelength_max=wl_max)

    if verbose:
        print(f"\n=== Evaluating z={redshift:.4f} ({line_type}) — "
              f"{pred['n_lines']} lines in range [{wl_min:.0f}–{wl_max:.0f}] ===")

    line_reports = []
    n_likely, n_marginal, n_not_found = 0, 0, 0

    for line in pred["lines"]:
        # Check which camera the line falls in
        obs_wl = line["obs_wl"]
        wclass = line["width_class"]
        w3s = WIDTH_3SIGMA.get(wclass, 25.0)

        # Find the right camera
        cam = None
        for c in "BRZ":
            cw = spectrum[c][0]
            if cw[0] <= obs_wl <= cw[-1]:
                cam = c
                break
        if cam is None:
            line_reports.append({
                **line, "status": "NOT_FOUND", "fit": None,
                "reason": "wavelength outside all cameras",
            })
            n_not_found += 1
            continue

        cam_w, cam_f, _ = spectrum[cam]

        # Check if this line is part of a known doublet
        found_doublet = None
        for dname, (wl1, wl2, sep, arat, dtype) in DOUBLET_PARAMS.items():
            if dtype != "emission" and wclass != "absorption":
                continue
            if abs(line["rest_wl"] - wl1) < 0.2:
                obs2 = wl2 * (1.0 + redshift)
                found_doublet = (dname, obs_wl, obs2, sep * (1.0 + redshift), arat, dtype)
                break
            if abs(line["rest_wl"] - wl2) < 0.2:
                obs1 = wl1 * (1.0 + redshift)
                found_doublet = (dname, obs1, obs_wl, sep * (1.0 + redshift), 1.0 / arat, dtype)
                break

        if found_doublet:
            dname, cg1, cg2, sep_obs, arat, dtype = found_doublet
            fit = fit_doublet(cam_w, cam_f, cg1, cg2,
                              line_type="emission" if dtype == "emission" else "absorption",
                              width_3sigma=w3s, separation_rest=sep_obs, amp_ratio_expected=arat)
            # Extract the relevant component
            if abs(cg1 - obs_wl) < abs(cg2 - obs_wl):
                comp = fit.get("component_1")
            else:
                comp = fit.get("component_2")
            # Add doublet info
            fit["doublet_name"] = dname
        else:
            fit = fit_peak(cam_w, cam_f, obs_wl, width_3sigma=w3s,
                           line_type=line["type"])
            comp = fit  # single peak, the fit IS the component

        # Determine status
        status, reason = _classify(comp, fit, obs_wl)

        if status == "LIKELY":    n_likely += 1
        elif status == "MARGINAL": n_marginal += 1
        else:                     n_not_found += 1

        report = {**line, "status": status, "reason": reason, "fit": fit}
        if verbose:
            extra = ""
            if status == "LIKELY":
                extra = f"  c={comp['center']:.1f} S/N={comp.get('local_snr', fit.get('local_snr','?'))} FWHM={comp.get('fwhm_km_s', fit.get('fwhm_km_s','?'))}"
            print(f"  [{status:9s}] {line['name']:12s} @ {obs_wl:.0f}Å  {extra}{' | ' + reason if reason else ''}")
        line_reports.append(report)

    n_pred = len(line_reports)
    score = (n_likely + 0.5 * n_marginal) / max(n_pred, 1)

    if verbose:
        print(f"  → {n_likely} likely, {n_marginal} marginal, {n_not_found} not found  "
              f"score={score:.2f}")

    return {
        "redshift": redshift,
        "line_type": line_type,
        "n_predicted": n_pred,
        "n_likely": n_likely,
        "n_marginal": n_marginal,
        "n_not_found": n_not_found,
        "score": round(score, 3),
        "lines": line_reports,
    }


def _classify(comp, fit, predicted_obs):
    """Classify a fit result as LIKELY / MARGINAL / NOT_FOUND."""
    if comp is None or comp.get("center") is None:
        if fit.get("flags") and "fit_failed" in fit["flags"]:
            return "NOT_FOUND", "fit_failed"
        return "NOT_FOUND", None

    local_snr = comp.get("local_snr") or fit.get("local_snr") or 0
    center_dev = abs(comp["center"] - predicted_obs)
    dchi2 = fit.get("delta_chi2_per_n") or 0

    reasons = []
    if local_snr >= LOCAL_SNR_LIKELY and center_dev <= CENTER_DEV_TOL:
        return "LIKELY", None
    elif local_snr >= LOCAL_SNR_MARGINAL:
        if center_dev > CENTER_DEV_TOL:
            reasons.append(f"center offset {center_dev:.1f}Å")
        if dchi2 <= 0:
            reasons.append("Δχ²/n ≤ 0")
        return "MARGINAL", "; ".join(reasons) if reasons else None
    else:
        if local_snr < LOCAL_SNR_MARGINAL:
            reasons.append(f"low S/N={local_snr:.1f}")
        if center_dev > CENTER_DEV_TOL:
            reasons.append(f"center offset {center_dev:.1f}Å")
        return "NOT_FOUND", "; ".join(reasons) if reasons else None


def compare_hypotheses(report_a: dict, report_b: dict, label_a: str, label_b: str) -> dict:
    """Compare two hypothesis evaluations and return a summary verdict.

    This is the CataLogA equivalent of FORMA's Hypothesis Synthesis agent.
    """
    score_a = report_a["score"]
    score_b = report_b["score"]
    verdict = "indeterminate"
    if score_a > score_b * 1.5:
        verdict = label_a
    elif score_b > score_a * 1.5:
        verdict = label_b
    elif score_a == score_b:
        verdict = "tie"

    lines = []
    names = set()
    for r in report_a.get("lines", []):
        names.add(r["name"])
    for r in report_b.get("lines", []):
        names.add(r["name"])

    for name in sorted(names):
        la = next((r for r in report_a.get("lines", []) if r["name"] == name), None)
        lb = next((r for r in report_b.get("lines", []) if r["name"] == name), None)
        lines.append({
            "name": name,
            f"{label_a}_status": la["status"] if la else "—",
            f"{label_a}_obs": la["obs_wl"] if la else None,
            f"{label_b}_status": lb["status"] if lb else "—",
            f"{label_b}_obs": lb["obs_wl"] if lb else None,
        })

    return {
        "verdict": verdict,
        f"{label_a}_score": score_a,
        f"{label_b}_score": score_b,
        "comparison": lines,
    }
