"""Pipeline-internal plotting — FORMA-compatible figure layout.

Generates two figure types per target, both in FORMA's 3-panel format
(spectrum+continuum, residual+absorption, residual+emission):

1. ``cwt_features.png`` — all CWT-detected features (FORMA ``plot_features``)
2. ``fa_cleaned_{label}.png`` — per-hypothesis LIKELY/MARGINAL lines
   (FORMA ``plot_harness_candidate``)

Conventions copied directly from FORMA ``utils/plot.py``:
  - SIGMA_TO_FWHM = 2.355
  - Line-type lookup via ``EMISSION_LINES`` / ``ABSORPTION_LINES``
  - CSV centre key fallback: ``fitted_center`` → ``predicted_obs``
  - Bracketed-name normalisation via ``_BRACKET_FIX``
"""

import csv
import os
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from cataloga.harness.tools import EMISSION_LINES, ABSORPTION_LINES

SIGMA_TO_FWHM = 2.355

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
    """Normalise LLM-produced line name for EMISSION/ABSORPTION lookup."""
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


# ── Shared 3-panel layout (FORMA style) ────────────────────

def _make_3panel_fig():
    """Return (fig, ax1, ax2, ax3) with FORMA's dimensions."""
    fig, axes = plt.subplots(3, 1, figsize=(16, 12), sharex=True)
    return fig, axes[0], axes[1], axes[2]


def _draw_spectrum_continuum(ax1, wl, fl, continuum_flux):
    """Panel 1: spectrum (black) + continuum (red dashed)."""
    ax1.plot(wl, fl, 'k-', lw=0.8, alpha=0.75, label='Spectrum')
    ax1.plot(wl, continuum_flux, 'r--', lw=1.5, alpha=0.9, label='Continuum')
    ax1.set_ylabel('flux')
    ax1.legend(fontsize=9, loc='upper right')
    ax1.grid(True, alpha=0.25)


def _draw_residual_panel(ax, wl, residual, color, label):
    """Panel 2/3: residual (steelblue) + zero line."""
    ax.plot(wl, residual, color='steelblue', lw=0.7, alpha=0.75, label=label)
    ax.axhline(0, color='gray', linestyle='-', linewidth=0.5, alpha=0.5)
    ax.set_ylabel('flux')
    ax.legend(fontsize=9, loc='upper right')
    ax.grid(True, alpha=0.25)


def _draw_gaussian(ax, center, amp, fwhm, color, is_absorption=False):
    """Draw ±3.5σ Gaussian profile at *center* (FORMA lines 264–269)."""
    if fwhm <= 0 or amp is None:
        return
    sigma = fwhm / SIGMA_TO_FWHM
    x = np.linspace(center - 3.5 * sigma, center + 3.5 * sigma, 200)
    y = -abs(amp) * np.exp(-0.5 * ((x - center) / sigma) ** 2) if is_absorption \
        else abs(amp) * np.exp(-0.5 * ((x - center) / sigma) ** 2)
    ax.plot(x, y, color=color, linewidth=1.8, alpha=0.85)


# ── CWT overview (FORMA plot_features) ─────────────────────

def plot_cwt_overview(wl, fl, continuum_flux, peaks, troughs, out_path):
    """FORMA-style 3-panel CWT feature overview."""
    fig, ax1, ax2, ax3 = _make_3panel_fig()
    residual = np.asarray(fl, dtype=np.float64) - np.asarray(continuum_flux, dtype=np.float64)

    # Panel 1: spectrum + continuum
    _draw_spectrum_continuum(ax1, wl, fl, continuum_flux)

    # Panel 2: residual + absorption
    _draw_residual_panel(ax2, wl, residual, 'steelblue', 'Residual')
    # Panel 3: residual + emission
    _draw_residual_panel(ax3, wl, residual, 'steelblue', 'Residual')

    text_y = np.max(residual) * 0.92
    n_em, n_abs = 0, 0

    for feats, color, is_abs, ax_target in [
        (peaks, 'darkorange', False, ax3),
        (troughs, 'tomato', True, ax2),
    ]:
        for f in feats:
            w = f.get('wavelength')
            if w is None or w <= 0:
                continue
            amp = f.get('amplitude', 0)
            fwhm = f.get('FWHM_A', f.get('FWHM(Å)'))
            if fwhm is None:
                sv = f.get('sigma')
                fwhm = sv * SIGMA_TO_FWHM if sv else 10.0

            if abs(amp) > 0 and fwhm > 0:
                _draw_gaussian(ax_target, w, amp, fwhm, color,
                               is_absorption=is_abs)
            ax_target.axvline(w, color=color, linestyle='--', linewidth=0.8, alpha=0.4)
            ax_target.text(w, text_y, f'{w:.1f}',
                           rotation=90, va='top', ha='center',
                           fontsize=7, color=color, alpha=0.8)
            if is_abs:
                n_abs += 1
            else:
                n_em += 1

    ax3.set_xlabel('wavelength')
    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  [plot] cwt_features: {n_em} em, {n_abs} abs → {out_path}")


# ── Per-hypothesis lines (FORMA plot_harness_candidate) ────

def plot_hypothesis_lines(wl, fl, continuum_flux, sh_csv_path, out_path,
                          redshift=None, title=""):
    """FORMA-style 3-panel plot for one hypothesis's adopted lines."""
    if not os.path.exists(sh_csv_path):
        return

    rows = []
    with open(sh_csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("status") or "").strip().upper() in ("LIKELY", "MARGINAL"):
                rows.append(row)

    if not rows:
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.text(0.5, 0.5, f"{title}: no LIKELY/MARGINAL lines",
                ha="center", va="center", fontsize=14, transform=ax.transAxes)
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return

    fig, ax1, ax2, ax3 = _make_3panel_fig()
    fl_arr = np.asarray(fl, dtype=np.float64)
    c_arr = np.asarray(continuum_flux, dtype=np.float64)
    residual = fl_arr - c_arr

    # Panel 1: spectrum + continuum
    _draw_spectrum_continuum(ax1, wl, fl_arr, c_arr)

    # Panel 2: residual + absorption
    _draw_residual_panel(ax2, wl, residual, 'steelblue', 'Residual')
    # Panel 3: residual + emission
    _draw_residual_panel(ax3, wl, residual, 'steelblue', 'Residual')

    text_y = np.max(residual) * 0.92
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
        fwhm = sigma_val * SIGMA_TO_FWHM if sigma_val else 10.0

        color = 'darkorange' if is_emission else 'tomato'
        ax = ax3 if is_emission else ax2

        if is_emission and amp is not None and amp > 0 and fwhm > 0:
            _draw_gaussian(ax, center, amp, fwhm, color, is_absorption=False)
        elif is_absorption and fwhm > 0:
            _draw_gaussian(ax, center, amp, fwhm, color, is_absorption=True)

        ax.axvline(center, color=color, linestyle='--', linewidth=0.8, alpha=0.4)
        ax.text(center, text_y, f'{name}\n{center:.1f}',
                rotation=90, va='top', ha='center',
                fontsize=6, color=color, alpha=0.8)

        if is_emission:
            n_em += 1
        else:
            n_abs += 1

    ax3.set_xlabel('wavelength')

    title_str = title or ""
    if redshift is not None:
        title_str = f"z = {redshift:.4f}  {title_str}"
    if title_str:
        fig.suptitle(title_str.strip(), fontsize=13, y=0.98)

    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  [plot] {title}: {n_em} em, {n_abs} abs → {out_path}")
