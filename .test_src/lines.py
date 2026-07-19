"""Spectral line tables and redshift prediction.

Loads the rest-frame wavelength catalogue from ``.knowledge/lines.md``
(the same Python-tuple format used by ``inspect_spectrum.py``) and provides
``predict_lines()`` — the analog of FORMA's harness/tools.py:EMISSION_LINES
+ predict_lines().
"""

import ast
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LINES_PATH = os.path.join(_REPO, ".knowledge", "lines.md")

# Line-width classification (same classification as FORMA)
LINE_WIDTHS = {
    "Lyα":       "broad",
    "C IV":      "broad",
    "He II":     "both",
    "C III]":    "broad",
    "Mg II":     "broad",
    "[Ne V]":    "narrow",
    "[O II]":    "narrow",
    "Hε":        "both",
    "Hδ":        "both",
    "Hγ":        "both",
    "Hβ":        "both",
    "Hα":        "both",
    "[O III]a":  "narrow",
    "[O III]b":  "narrow",
    "[N II]a":   "narrow",
    "[N II]b":   "narrow",
    "[S II]a":   "narrow",
    "[S II]b":   "narrow",
    "Ca K":      "absorption",
    "Ca H":      "absorption",
    "G-band":    "absorption",
    "Mg I":      "absorption",
    "Na D":      "absorption",
    "CaT1":      "absorption",
    "CaT2":      "absorption",
    "CaT3":      "absorption",
}

WIDTH_3SIGMA = {"broad": 90.0, "narrow": 25.0, "both": 50.0, "absorption": 20.0}

# Known doublet rest-frame parameters (name → (wl1, wl2, sep_Å, amp_ratio_hint))
DOUBLET_PARAMS = {
    "Ca H/K":   (3934.8, 3969.6, 34.8, 0.5, "absorption"),
    "O III":    (4960.3, 5008.2, 47.9, 3.0, "emission"),
    "S II":     (6718.3, 6732.7, 14.4, 1.0, "emission"),
    "N II":     (6549.8, 6585.3, 35.5, 3.0, "emission"),
    "Na D":     (5891.6, 5897.6,  6.0, 2.0, "absorption"),
}


def load_lines():
    """Return ``[(wavelength_Å, name), …]`` sorted by wavelength."""
    with open(_LINES_PATH) as fh:
        pairs = ast.literal_eval("[" + fh.read() + "]")
    pairs.sort(key=lambda x: x[0])
    return pairs


def predict_lines(
    redshift: float,
    line_type: str = "all",
    wavelength_min: float = None,
    wavelength_max: float = None,
):
    """Predict observed-frame wavelengths for rest-frame lines at redshift *z*.

    Parameters
    ----------
    redshift : float
    line_type : "emission", "absorption", or "all"
    wavelength_min, wavelength_max : float, optional
        Filter to observed wavelengths within [min, max].

    Returns
    -------
    dict with keys ``redshift``, ``n_lines``, and ``lines`` (list of dicts,
    each with ``name``, ``rest_wl``, ``obs_wl``, ``width_class``, ``type``).
    """
    all_lines = load_lines()
    out = []

    for rest_wl, name in all_lines:
        wclass = LINE_WIDTHS.get(name, "narrow")
        if line_type == "emission" and wclass == "absorption":
            continue
        if line_type == "absorption" and wclass != "absorption":
            continue

        obs_wl = rest_wl * (1.0 + redshift)
        if wavelength_min is not None and obs_wl < wavelength_min:
            continue
        if wavelength_max is not None and obs_wl > wavelength_max:
            continue

        out.append({
            "name": name,
            "rest_wl": round(rest_wl, 1),
            "obs_wl": round(obs_wl, 1),
            "width_class": wclass,
            "type": "absorption" if wclass == "absorption" else "emission",
        })

    out.sort(key=lambda x: x["obs_wl"])
    return {"redshift": redshift, "n_lines": len(out), "lines": out}
