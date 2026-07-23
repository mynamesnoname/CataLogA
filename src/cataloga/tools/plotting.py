"""Pipeline-internal plotting — called by PipelineRunner after VI and FA.

Generates:
- ``cwt_features.png`` — all CWT-detected features on full spectrum
- ``fa_cleaned_{label}.png`` — per-hypothesis LIKELY/MARGINAL lines

Adapted from FORMA ``plot.py`` conventions (line-name normalisation,
CSV key fallbacks, σ→FWHM, bracket-fix lookup).
"""

import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from cataloga.harness.tools import EMISSION_LINES, ABSORPTION_LINES

SIGMA_TO_FWHM = 2.35482

_BRACKET_FIX: dict[str, str] = {
    "O[II]": "[O II]", "N[II]a": "[N II]a", "N[II]b": "[N II]b",
    "S[II]a": "[S II]a", "S[II]b": "[S II]b",
    "O[III]a": "[O III]a", "O[III]b": "[O III]b", "Ne[V]": "[Ne V]",
    "O II": "[O II]", "O IIIa": "[O III]a", "O IIIb": "[O III]b",
    "N IIa": "[N II]a", "N IIb": "[N II]b",
    "S IIa": "[S II]a", "S IIb": "[S II]b", "Ne V": "[Ne V]",
    "Mg_abs": "Mg I_abs",
}


def _lookup_name(raw: str) -> str:
    import re
    if not raw:
        return ""
    cleaned = re.sub(r'([A-Za-z]+)\s+\[([IVab]+)\]', r'\1[\2]', raw.strip())
    return _BRACKET_FIX.get(cleaned, cleaned)


def _safe_float(row, *keys):
    for k in keys:
        val = row.get(k)
        if val and str(val).strip() not in ("", "—", "-", "N/A"):
            try:
                return float(val)
            except (ValueError, TypeError):
                continue
    return None


def _arm_boundaries(axes):
    """Mark B/R and R/Z arm overlap zones."""
    for ax in axes:
        for x, ls in [(5760, ":"), (5800, ":"), (7520, "--"), (7620, "--")]:
            ax.axvline(x, color="gray", linestyle=ls, linewidth=0.5, alpha=0.5)


def plot_cwt_overview(wl, fl, peaks, troughs, out_path):
    """Full spectrum with all CWT features marked (Gaussian profiles + labels)."""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 8), sharex=True,
                                    gridspec_kw={"height_ratios": [3, 1]})
    ax1.plot(wl, fl, "k-", lw=0.6, alpha=0.7)
    ax1.set_ylabel("flux")
    ax1.grid(True, alpha=0.2)

    y_min, y_max = np.nanpercentile(fl, [1, 99])
    yr = y_max - y_min
    label_y = y_max + yr * 0.05

    for feats, color, is_abs in [(peaks, "darkorange", False),
                                  (troughs, "tomato", True)]:
        for f in feats:
            w = f.get("wavelength")
            if w is None or w <= 0:
                continue
            amp = f.get("amplitude", 0)
            fwhm = f.get("FWHM_A") or 15.0
            ax1.axvline(w, color=color, linestyle="--", linewidth=0.7, alpha=0.35)
            if fwhm > 0:
                sigma = fwhm / SIGMA_TO_FWHM
                x = np.linspace(w - 3.5 * sigma, w + 3.5 * sigma, 150)
                y = -abs(amp) * np.exp(-0.5 * ((x - w) / sigma) ** 2) if is_abs \
                    else abs(amp) * np.exp(-0.5 * ((x - w) / sigma) ** 2)
                ax1.plot(x, y, color=color, linewidth=1.5, alpha=0.8)
            ax1.text(w, label_y, f"{'ab' if is_abs else 'em'}({f.get('snr','?'):.0f})",
                     rotation=90, va="bottom", ha="center",
                     fontsize=5.5, color=color, alpha=0.7)

    ax1.set_title(f"CWT Features  ({len(peaks)} em, {len(troughs)} abs)", fontsize=10)
    ax1.legend(["spectrum"], fontsize=8, loc="upper right")

    ax2.plot(wl, np.abs(fl), "steelblue", lw=0.5, alpha=0.6)
    ax2.set_ylabel("|flux|")
    ax2.set_xlabel("wavelength (Å)")
    ax2.grid(True, alpha=0.2)
    _arm_boundaries([ax1, ax2])

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_hypothesis_lines(wl, fl, sh_csv_path, out_path, label=""):
    """Spectrum with LIKELY/MARGINAL lines from one SH line catalog."""
    if not os.path.exists(sh_csv_path):
        return

    rows = []
    with open(sh_csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("status", "").strip() in ("LIKELY", "MARGINAL"):
                rows.append(row)

    if not rows:
        fig, ax = plt.subplots(figsize=(18, 6))
        ax.text(0.5, 0.5, f"{label}: no LIKELY/MARGINAL lines",
                ha="center", va="center", fontsize=14, transform=ax.transAxes)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(18, 8), sharex=True,
                                    gridspec_kw={"height_ratios": [3, 1]})
    ax1.plot(wl, fl, "k-", lw=0.6, alpha=0.7, label="spectrum")
    ax1.set_ylabel("flux")
    ax1.grid(True, alpha=0.2)

    y_min, y_max = np.nanpercentile(fl, [1, 99])
    yr = y_max - y_min
    label_y = y_max + yr * 0.05

    n_em, n_abs = 0, 0

    for row in rows:
        name = row.get("name", "")
        lookup = _lookup_name(name)
        is_emission = lookup in EMISSION_LINES
        is_absorption = lookup in ABSORPTION_LINES
        if not is_emission and not is_absorption:
            continue

        center = _safe_float(row, "fitted_center", "predicted_obs")
        if center is None:
            continue

        amp = _safe_float(row, "amplitude")
        sigma_val = _safe_float(row, "fitted_sigma")
        fwhm = sigma_val * SIGMA_TO_FWHM if sigma_val else 15.0
        color = "darkorange" if is_emission else "tomato"

        ax1.axvline(center, color=color, linestyle="--", linewidth=0.7, alpha=0.35)
        if fwhm > 0:
            s = fwhm / SIGMA_TO_FWHM
            x = np.linspace(center - 3.5 * s, center + 3.5 * s, 150)
            y = -abs(amp or 0) * np.exp(-0.5 * ((x - center) / s) ** 2) if is_absorption \
                else abs(amp or 0) * np.exp(-0.5 * ((x - center) / s) ** 2)
            ax1.plot(x, y, color=color, linewidth=1.5, alpha=0.8)
        ax1.text(center, label_y, f"{lookup}\n{center:.1f}",
                 rotation=90, va="bottom", ha="center",
                 fontsize=5.5, color=color, alpha=0.7)

        if is_emission:
            n_em += 1
        else:
            n_abs += 1

    ax1.set_title(f"{label}  ({n_em} em, {n_abs} abs)", fontsize=10)
    ax1.legend(["spectrum"], fontsize=8, loc="upper right")

    ax2.plot(wl, np.abs(fl), "steelblue", lw=0.5, alpha=0.6)
    ax2.set_ylabel("|flux|")
    ax2.set_xlabel("wavelength (Å)")
    ax2.grid(True, alpha=0.2)
    _arm_boundaries([ax1, ax2])

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
