"""LLM-callable @tool functions — ported from FORMA ``harness/tools.py``.

Adapted for CataLogA's FITS-based workflow.  Tools can be used standalone
(loading spectrum from file) or via **closure binding** where spectrum arrays
are captured at agent creation time (zero file I/O per call).

Closure pattern (from FORMA)::

    wl, fl, iv = load_spectrum_arrays(coadd_path, targetid)
    tools = build_tools(wl, fl, iv, kb_dir=...)

The returned tool list can be passed to ``langchain.agents.create_agent()``.
"""

import re
import os
import csv
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Rest-frame line tables (same as FORMA's EMISSION/ABSORPTION_LINES)
# ---------------------------------------------------------------------------

EMISSION_LINES = {
    "Lyα": 1216.0, "C IV": 1549.0, "He II": 1640.4, "C III]": 1909.0,
    "Mg II": 2800.0, "[Ne V]": 3426.0, "[O II]": 3727.0,
    "Hε": 3970.1, "Hδ": 4102.9, "Hγ": 4341.7, "Hβ": 4862.7,
    "[O III]a": 4960.3, "[O III]b": 5008.2,
    "[N II]a": 6549.8, "Hα": 6564.6, "[N II]b": 6585.3,
    "[S II]a": 6718.3, "[S II]b": 6732.7,
}

EMISSION_LINE_WIDTHS = {
    "Lyα": "broad", "C IV": "broad", "C III]": "broad",
    "He II": "both", "Mg II": "broad",
    "Hε": "both", "Hδ": "both", "Hγ": "both", "Hβ": "both", "Hα": "both",
    "[Ne V]": "narrow", "[O II]": "narrow",
    "[O III]a": "narrow", "[O III]b": "narrow",
    "[N II]a": "narrow", "[N II]b": "narrow",
    "[S II]a": "narrow", "[S II]b": "narrow",
}

ABSORPTION_LINES = {
    "Ca K_abs": 3934.8, "Ca H_abs": 3969.6, "G-band_abs": 4305.6,
    "Mg I_abs": 5176.7, "Mg II_abs": 2800.0, "Na D_abs": 5895.6,
    "CaT1_abs": 8498.0, "CaT2_abs": 8542.0, "CaT3_abs": 8662.0,
    "Hε_abs": 3970.1, "Hδ_abs": 4102.9, "Hγ_abs": 4341.7,
    "Hβ_abs": 4862.7, "Hα_abs": 6564.6,
}

WIDTH_3SIGMA_MAP = {"broad": 90.0, "narrow": 25.0, "both": 50.0, "absorption": 20.0}

DOUBLET_PARAMS = {
    "Ca H/K": (3934.8, 3969.6, 34.8, 0.5, "absorption"),
    "O III": (4960.3, 5008.2, 47.9, 3.0, "emission"),
    "S II": (6718.3, 6732.7, 14.4, 1.0, "emission"),
    "N II": (6549.8, 6585.3, 35.5, 3.0, "emission"),
    "Na D": (5891.6, 5897.6, 6.0, 2.0, "absorption"),
}

# ---------------------------------------------------------------------------
# Internal fitting core (reuses cataloga.tools.fitting)
# ---------------------------------------------------------------------------

def _do_fit_peak(wl, fl, center_guess, width_3sigma=25.0, line_type="emission",
                 window_half=200.0) -> dict:
    """Delegate to ``cataloga.tools.fitting.fit_peak``."""
    from cataloga.tools.fitting import fit_peak
    return fit_peak(wl, fl, center_guess, width_3sigma, line_type, window_half)


def _detect_oii_core(wavelength, flux, target_wl, search_window=25.0) -> dict:
    """Delegate to ``cataloga.tools.detect.detect_oii_slope_change``."""
    from cataloga.tools.detect import detect_oii_slope_change
    r = detect_oii_slope_change(wavelength, flux, target_wl, search_window)
    r["note"] = ("Designed for the NARROW [O II] 3727 doublet. On broad lines "
                 "(e.g. QSO Lyα / C IV) the returned FWHM measures only the "
                 "sharpest sub-structure inside the window and is NOT the line "
                 "width — judge line breadth from read_spectrum_region instead.")
    return r


# ---------------------------------------------------------------------------
# Doublet fitting (reuses cataloga.tools.fitting)
# ---------------------------------------------------------------------------

def _do_fit_doublet(wl, fl, center_guess_1, center_guess_2,
                    line_type="emission", width_3sigma=25.0, window_half=300.0,
                    separation_rest=None, separation_tolerance=5.0,
                    amp_ratio_expected=None) -> dict:
    """Delegate to ``cataloga.tools.fitting.fit_doublet``."""
    from cataloga.tools.fitting import fit_doublet
    return fit_doublet(wl, fl, center_guess_1, center_guess_2,
                       line_type, width_3sigma, window_half,
                       separation_rest, separation_tolerance, amp_ratio_expected)


# ---------------------------------------------------------------------------
# Knowledge base search
# ---------------------------------------------------------------------------

def _find_kb_dir() -> Path:
    """Resolve kb/ directory."""
    p = Path(__file__).resolve().parent.parent / "data" / "kb"
    if p.exists():
        return p
    raise FileNotFoundError("KB directory not found")


def grep_kb(pattern: str, A: int = 0, B: int = 0, C: int = 0) -> dict:
    """Search knowledge base files with optional context lines.

    Parameters
    ----------
    pattern : str — grep-compatible regex (case-insensitive)
    A, B, C : int — context lines (like grep -A/-B/-C)

    Returns
    -------
    dict mapping filename → list of match blocks
    """
    kb_dir = _find_kb_dir()
    context_before = max(B, C)
    context_after = max(A, C)
    results = {}

    for fpath in sorted(kb_dir.glob("*.md")):
        lines = fpath.read_text(encoding="utf-8").split("\n")
        match_lines = set()
        for i, line in enumerate(lines, start=1):
            if re.search(pattern, line, re.IGNORECASE):
                match_lines.add(i)
        if not match_lines:
            continue

        windows = []
        for ln in sorted(match_lines):
            start = max(1, ln - context_before)
            end = min(len(lines), ln + context_after)
            windows.append((start, end))

        # Merge overlapping windows
        merged = []
        for s, e in windows:
            if merged and s <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))

        blocks = []
        for s, e in merged:
            block = []
            for ln in range(s, e + 1):
                marker = ">" if ln in match_lines else " "
                block.append(f"L{ln}{marker}: {lines[ln-1].strip()[:200]}")
            blocks.append(block)

        results[fpath.name] = blocks[:20]  # cap at 20 blocks per file

    return results if results else {"(no matches)": []}


# ---------------------------------------------------------------------------
# Predict lines at redshift
# ---------------------------------------------------------------------------

def predict_lines(redshift: float, line_type: str = "all",
                  wavelength_min: float = None, wavelength_max: float = None) -> dict:
    """Predict observed-frame wavelengths for all lines at redshift z."""
    lines_out = []
    if line_type in ("emission", "all"):
        for name, rest_wl in EMISSION_LINES.items():
            obs_wl = rest_wl * (1 + redshift)
            if wavelength_min is not None and obs_wl < wavelength_min:
                continue
            if wavelength_max is not None and obs_wl > wavelength_max:
                continue
            lines_out.append({"name": name, "rest_wl": rest_wl, "obs_wl": round(obs_wl, 1),
                              "width_class": EMISSION_LINE_WIDTHS.get(name, "narrow"), "type": "emission"})
    if line_type in ("absorption", "all"):
        for name, rest_wl in ABSORPTION_LINES.items():
            obs_wl = rest_wl * (1 + redshift)
            if wavelength_min is not None and obs_wl < wavelength_min:
                continue
            if wavelength_max is not None and obs_wl > wavelength_max:
                continue
            lines_out.append({"name": name, "rest_wl": rest_wl, "obs_wl": round(obs_wl, 1),
                              "width_class": "absorption", "type": "absorption"})
    lines_out.sort(key=lambda x: x["obs_wl"])
    return {"redshift": redshift, "n_lines": len(lines_out), "lines": lines_out}


def compute_redshift(observed_wavelength: float, rest_wavelength: float) -> dict:
    """z = λ_obs / λ_rest − 1"""
    z = observed_wavelength / rest_wavelength - 1.0
    return {"redshift": round(z, 6), "rest_wavelength": rest_wavelength,
            "observed_wavelength": observed_wavelength}


def compute_redshift_error(rest_wavelength: float, wavelength_error: float) -> dict:
    """σ_z = wavelength_error / rest_wavelength"""
    return {"sigma_z": round(wavelength_error / rest_wavelength, 6),
            "rest_wavelength": rest_wavelength, "wavelength_error": wavelength_error}


# ---------------------------------------------------------------------------
# Spectrum region reader
# ---------------------------------------------------------------------------

def read_spectrum_region(wl: np.ndarray, fl: np.ndarray, iv: np.ndarray = None,
                         wl_min: float = None, wl_max: float = None):
    """Read a raw slice of the spectrum.  When used as a closure, wl/fl/iv are
    captured arrays and wl_min/wl_max are the only required arguments.

    Returns (wl_range, wl_list, fl_list).
    """
    # Handle both closure and explicit calls
    if wl_min is None and wl_max is None:
        raise ValueError("wl_min and wl_max required")
    mask = (wl >= wl_min) & (wl <= wl_max)
    return {
        "wl_range": [wl_min, wl_max],
        "n": int(np.sum(mask)),
        "wl": [round(float(x), 3) for x in wl[mask]],
        "fl": [round(float(x), 4) for x in fl[mask]],
    }


# ---------------------------------------------------------------------------
# Output tools
# ---------------------------------------------------------------------------

def write_report(file_path: str, content: str) -> dict:
    """Write a markdown report."""
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    return {"path": file_path, "size_bytes": len(content.encode("utf-8"))}


def write_lines_csv(file_path: str, lines: list) -> dict:
    """Write per-hypothesis line catalog CSV."""
    columns = ["name", "rest_wavelength", "predicted_obs", "fitted_center",
               "fitted_center_err", "amplitude", "amplitude_err", "fitted_sigma",
               "fwhm_km_s", "ridge_length", "cwt_snr", "status"]
    os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(lines)
    return {"path": file_path, "n_lines": len(lines)}


# ---------------------------------------------------------------------------
# Tool builder — closure binding (FORMA pattern)
# ---------------------------------------------------------------------------

def build_tools(wavelength, flux, ivar=None, kb_dir=None):
    """Build LLM-callable tools with spectrum arrays captured via closure.

    This is the key FORMA pattern: arrays are loaded once, then tools
    reference them without file I/O.

    Returns a list of callable tools suitable for LangChain's create_agent().
    """
    _wl = np.asarray(wavelength, dtype=float)
    _fl = np.asarray(flux, dtype=float)
    _iv = np.asarray(ivar, dtype=float) if ivar is not None else None

    def _fit_peak(center_guess: float, width_3sigma: float = 25.0,
                  line_type: str = "emission", window_half: float = 200.0) -> dict:
        """Fit a Gaussian + linear baseline at a predicted λ_obs.

        Args:
            center_guess: Predicted observed wavelength (Å)
            width_3sigma: expected 3σ width — broad=90, narrow=25, both=50, absorption=20
            line_type: "emission" or "absorption"
            window_half: half-width of fitting window (default 200 Å)
        """
        return _do_fit_peak(_wl, _fl, center_guess, width_3sigma, line_type, window_half)

    def _read_spectrum_region(wl_min: float, wl_max: float) -> dict:
        """Read a raw spectrum slice.  Use to investigate suspicious regions.

        Args:
            wl_min, wl_max: wavelength range of interest (Å)
        """
        return read_spectrum_region(_wl, _fl, _iv, wl_min, wl_max)

    def _detect_oii_slope_change(target_wl: float, search_window: float = 25.0) -> dict:
        """Detect [O II] unresolved-doublet morphology at a claimed position.

        Args:
            target_wl: observed wavelength where [O II] is claimed
            search_window: half-width of search window (default 25 Å)
        """
        return _detect_oii_core(_wl, _fl, target_wl, search_window)

    def _fit_doublet(center_guess_1: float, center_guess_2: float,
                     line_type: str = "emission", width_3sigma: float = 25.0,
                     window_half: float = 300.0, separation_rest: float = None,
                     separation_tolerance: float = 5.0,
                     amp_ratio_expected: float = None) -> dict:
        """Fit two Gaussians + linear baseline for a close line pair.

        Args:
            center_guess_1, center_guess_2: predicted λ_obs of both components
            line_type: "emission" or "absorption"
            width_3sigma: expected 3σ width — broad=90, narrow=25, both=50
            window_half: half-width of fitting window
            separation_rest: expected rest-frame separation (Å) for validation
            separation_tolerance: allowed deviation from expected separation
            amp_ratio_expected: expected amplitude ratio |C2|/|C1|
        """
        return _do_fit_doublet(_wl, _fl, center_guess_1, center_guess_2,
                               line_type, width_3sigma, window_half,
                               separation_rest, separation_tolerance,
                               amp_ratio_expected)

    return [
        _fit_peak,
        _fit_doublet,
        _read_spectrum_region,
        _detect_oii_slope_change,
        grep_kb,
        predict_lines,
        compute_redshift,
        compute_redshift_error,
        write_report,
        write_lines_csv,
    ]


# ---------------------------------------------------------------------------
# Dual-spectrum tool builder
# ---------------------------------------------------------------------------

def build_dual_tools(wl_a, fl_a, wl_b, fl_b):
    """Build tools with access to TWO spectra (A and B repeats).

    ``read_spectrum_region`` and ``detect_oii_slope_change`` accept a
    ``spec`` parameter: ``"A"`` or ``"B"``.

    ``fit_peak`` and ``fit_doublet`` operate on spectrum A (SH-H1) or
    spectrum B (SH-H2) — use separate ``build_tools()`` calls for each SH.
    """
    _wl_a = np.asarray(wl_a, dtype=float); _fl_a = np.asarray(fl_a, dtype=float)
    _wl_b = np.asarray(wl_b, dtype=float); _fl_b = np.asarray(fl_b, dtype=float)

    def _read_spec(spec: str, wl_min: float, wl_max: float) -> dict:
        """Read a slice from spectrum A or B.

        Args:
            spec: "A" or "B"
            wl_min, wl_max: wavelength range (Å)
        """
        if spec.upper() not in ("A", "B"):
            raise ValueError(f"spec must be 'A' or 'B', got {spec!r}")
        wl = _wl_a if spec.upper() == "A" else _wl_b
        fl = _fl_a if spec.upper() == "A" else _fl_b
        return read_spectrum_region(wl, fl, None, wl_min, wl_max)

    def _detect_oii(spec: str, target_wl: float, search_window: float = 25.0) -> dict:
        """Run OII slope-change detection on spectrum A or B.

        Args:
            spec: "A" or "B"
            target_wl: observed wavelength where [O II] is claimed
            search_window: half-width of search window (default 25 Å)
        """
        if spec.upper() not in ("A", "B"):
            raise ValueError(f"spec must be 'A' or 'B', got {spec!r}")
        wl = _wl_a if spec.upper() == "A" else _wl_b
        fl = _fl_a if spec.upper() == "A" else _fl_b
        return _detect_oii_core(wl, fl, target_wl, search_window)

    return [
        _read_spec,
        _detect_oii,
        grep_kb,
        write_report,
    ]
