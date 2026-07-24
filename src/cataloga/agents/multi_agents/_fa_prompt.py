"""Feature Auditor Agent.

Cross-hypothesis spectrum verification — reads the raw spectrum at each
claimed feature wavelength and determines whether the feature is physically
real or a noise artifact.

Adapted from FORMA's AnalysisAuditor / feature_audit_skill.md.
The skill prompt lives in ``skills/FA_skill.md``.

The FA receives line catalogs from multiple hypotheses and produces a
cleaned feature catalog (KEEP / FLAG / REMOVE) forward to Hypothesis Synthesis.
"""

import numpy as np

from cataloga.tools.spectrum import load_coadd_spectrum, merged_spectrum
from cataloga.tools.lines import DOUBLET_PARAMS

# ---------------------------------------------------------------------------
# Build the FA user message — contradiction matrix + doublet pairs + OII claims
# ---------------------------------------------------------------------------

def _collect_claims(line_catalogs: list[dict]) -> dict:
    """Merge per-hypothesis line catalogs into a unified claim matrix.

    Each catalog = {'hypothesis_idx': int, 'label': str, 'z': float,
                    'spectype': str, 'lines': list[dict]}

    Returns a dict keyed by observed wavelength (rounded to 1 decimal place)
    mapping to list of (hypothesis_index, line_info) tuples.
    """
    matrix = {}
    for cat in line_catalogs:
        idx = cat["hypothesis_idx"]
        for line in cat.get("lines", []):
            status = line.get("status", "LIKELY")
            if status not in ("LIKELY", "MARGINAL"):
                continue
            wl_key = round(line["obs_wl"], 1)
            if wl_key not in matrix:
                matrix[wl_key] = []
            matrix[wl_key].append((idx, line))
    return matrix


def _find_doublet_claims(line_catalogs: list[dict]) -> list[dict]:
    """Find all doublet (complete pairs and orphans) from line catalogs."""
    pairs = []
    for cat in line_catalogs:
        idx = cat["hypothesis_idx"]
        z = cat["z"]
        lines = cat.get("lines", [])
        line_names = {(ln["name"], ln.get("status", "LIKELY"))
                      for ln in lines if ln.get("status") in ("LIKELY", "MARGINAL")}

        for dname, (wl1, wl2, sep, arat, dtype) in DOUBLET_PARAMS.items():
            names = dname.split("/") if "/" in dname else [dname]
            # This is approximate — we need to match the actual doublet identification
            obs1 = wl1 * (1 + z)
            obs2 = wl2 * (1 + z)
            has_a = any(abs(ln["rest_wl"] - wl1) < 0.5 and ln.get("status") in ("LIKELY", "MARGINAL")
                       for ln in lines)
            has_b = any(abs(ln["rest_wl"] - wl2) < 0.5 and ln.get("status") in ("LIKELY", "MARGINAL")
                       for ln in lines)
            if has_a and has_b:
                pairs.append({
                    "hypothesis_idx": idx,
                    "name_a": f"{dname.split('/')[0] if '/' in dname else dname}a",
                    "name_b": f"{dname.split('/')[0] if '/' in dname else dname}b",
                    "wl_a": round(obs1, 1), "wl_b": round(obs2, 1),
                    "ratio_expected": f"a/b ≈ {arat:.1f}" if dtype == "emission" else "K deeper than H",
                    "complete": True,
                })
            elif has_a and not has_b:
                pairs.append({
                    "hypothesis_idx": idx,
                    "name_a": f"{dname.split('/')[0] if '/' in dname else dname}a",
                    "wl_a": round(obs1, 1),
                    "name_b": f"missing_{dname.split('/')[-1] if '/' in dname else dname}b",
                    "wl_b": None, "ratio_expected": "orphan",
                    "complete": False,
                })
    return pairs


def _find_oii_claims(line_catalogs: list[dict]) -> list[dict]:
    """Collect all [O II] claims from line catalogs."""
    claims = []
    for cat in line_catalogs:
        for line in cat.get("lines", []):
            if line["name"] == "[O II]" and line.get("status") in ("LIKELY", "MARGINAL"):
                claims.append({
                    "hypothesis_idx": cat["hypothesis_idx"],
                    "wl_obs": line["obs_wl"],
                    "status": line["status"],
                })
    return claims


def _find_lya_claims(line_catalogs: list[dict]) -> list[dict]:
    """Collect all Lyα claims."""
    claims = []
    for cat in line_catalogs:
        for line in cat.get("lines", []):
            if line["name"] == "Lyα" and line.get("status") in ("LIKELY", "MARGINAL"):
                claims.append({
                    "hypothesis_idx": cat["hypothesis_idx"],
                    "wl_obs": line["obs_wl"],
                    "status": line["status"],
                })
    return claims


def build_user_message(
    coadd_path: str,
    targetid: int,
    line_catalogs: list[dict],
) -> str:
    """Build the FA user prompt.

    Parameters
    ----------
    coadd_path : str
        Path to the coadd FITS file.
    targetid : int
    line_catalogs : list[dict]
        Each catalog: {'hypothesis_idx': int, 'label': str, 'z': float,
                       'spectype': str, 'lines': list[dict]}

    Returns
    -------
    str — the user message.
    """
    matrix = _collect_claims(line_catalogs)
    doublets = _find_doublet_claims(line_catalogs)
    oii_claims = _find_oii_claims(line_catalogs)
    lya_claims = _find_lya_claims(line_catalogs)

    # Load spectrum for summary
    sp = load_coadd_spectrum(coadd_path, targetid)
    w_all, f_all, iv_all = merged_spectrum(sp)
    wl_min, wl_max = float(np.nanmin(w_all)), float(np.nanmax(w_all))
    noise = 1.0 / np.sqrt(np.maximum(iv_all, 1e-30))
    valid = np.isfinite(noise) & (noise < 1e10)
    if valid.sum() > 100:
        snr_median = float(np.nanmedian(np.abs(f_all)[valid] / noise[valid]))
    else:
        snr_median = float(np.nanmedian(np.abs(f_all) / np.nanstd(f_all)))

    # Hypothesis summary
    hyp_lines = []
    for cat in line_catalogs:
        n_tot = len(cat.get("lines", []))
        n_likely = sum(1 for l in cat.get("lines", [])
                       if l.get("status") == "LIKELY")
        n_marginal = sum(1 for l in cat.get("lines", [])
                         if l.get("status") == "MARGINAL")
        hyp_lines.append(
            f"| {cat['label']} | z={cat['z']:.4f} | "
            f"{cat['spectype']} | {n_likely} likely | {n_marginal} marginal | "
            f"{n_tot} total |"
        )

    hyp_summary = (
        "## Hypotheses Under Review\n\n"
        "| Index | Redshift | Spectype | LIKELY | MARGINAL | Total |\n"
        "|-------|----------|----------|--------|----------|-------|\n"
        + "\n".join(hyp_lines) + "\n"
    )

    # Spectrum summary
    spec_summary = (
        "## Spectrum Summary\n\n"
        f"| FITS | `{coadd_path}` |\n"
        f"| TARGETID | {targetid} |\n"
        f"| Wavelength | {wl_min:.1f} – {wl_max:.1f} Å |\n"
        f"| Median SNR | {snr_median:.1f} |\n"
    )

    # Feature contradiction matrix
    matrix_lines = []
    matrix_lines.append(
        "## Feature Contradiction Matrix\n\n"
        "Each row = unique observed wavelength claimed by ≥1 hypothesis.\n"
    )
    header = "| λ_obs (Å) |"
    for cat in line_catalogs:
        header += f" {cat['label']} |"
    header += " Type |"
    matrix_lines.append(header)
    sep = "|" + "|".join(["-------"] * (2 + len(line_catalogs))) + "|"
    matrix_lines.append(sep)

    for wl_key in sorted(matrix.keys()):
        claims = matrix[wl_key]
        row = f"| {wl_key:.1f} |"
        for cat in line_catalogs:
            match = [c for c in claims if c[0] == cat["hypothesis_idx"]]
            if match:
                line = match[0][1]
                status_mark = " (M)" if line.get("status") == "MARGINAL" else ""
                row += f" {line['name']}{status_mark} |"
            else:
                row += " — |"
        ftype = "emission" if claims[0][1].get("type") == "emission" else "absorption"
        row += f" {ftype} |"
        # Edge zone markers
        if wl_key < 4000:
            row += " 🔵"
        elif wl_key > 7800:
            row += " 🔴"
        matrix_lines.append(row)
    matrix_lines.append("")

    # Edge zone legend
    matrix_lines.append("🔵 Blue edge (< 4000 Å): throughput collapse, non-Gaussian noise.")
    matrix_lines.append("🔴 OH zone (> 7800 Å): OH airglow residuals, identification risk.")
    matrix_lines.append("(M) = MARGINAL status (no marker = LIKELY in SH output).\n")

    # Doublet pairs & orphans
    doublet_lines = ["## Doublet Pairs & Orphans\n"]
    if doublets:
        for d in doublets:
            if d["complete"]:
                doublet_lines.append(
                    f"- H{d['hypothesis_idx'] + 1}: {d['name_a']}@{d['wl_a']} + "
                    f"{d['name_b']}@{d['wl_b']} → expected ratio {d['ratio_expected']}"
                )
            else:
                doublet_lines.append(
                    f"- H{d['hypothesis_idx'] + 1}: {d['name_a']}@{d['wl_a']} → "
                    f"ORPHAN — missing {d['name_b']}"
                )
    else:
        doublet_lines.append("(No doublet pairs identified.)")
    doublet_lines.append("")

    # [O II] claims
    oii_lines = ["## [O II] Morphology Check Required\n"]
    if oii_claims:
        for c in oii_claims:
            oii_lines.append(
                f"- H{c['hypothesis_idx'] + 1}: [O II] claimed at {c['wl_obs']:.1f} Å "
                f"(status: {c['status']}). Call `detect_oii_slope_change`."
            )
    else:
        oii_lines.append("(No [O II] claims.)")
    oii_lines.append("")

    # Lyα claims
    lya_lines = ["## Lyα Forest Check Required\n"]
    if lya_claims:
        for c in lya_claims:
            lya_lines.append(
                f"- H{c['hypothesis_idx'] + 1}: Lyα claimed at {c['wl_obs']:.1f} Å "
                f"(status: {c['status']}). Check for Lyα forest blueward."
            )
    else:
        lya_lines.append("(No Lyα claims.)")
    lya_lines.append("")

    return (
        hyp_summary + "\n"
        + spec_summary + "\n"
        + "\n".join(matrix_lines) + "\n"
        + "\n".join(doublet_lines) + "\n"
        + "\n".join(oii_lines) + "\n"
        + "\n".join(lya_lines)
        + "\n## Instructions\n\n"
        "1. Survey the Contradiction Matrix — note single vs multi-hypothesis rows,"
        " edge zone markers, doublet annotations.\n"
        "2. Batch-read ALL claimed wavelengths (±100 Å) using `read_spectrum_region`.\n"
        "3. Apply the Three-Question Test (peak clarity, width sanity, neighborhood"
        " comparison) to EVERY feature.\n"
        "4. Verify doublets — check both components independently.\n"
        "5. If [O II] is claimed, call `detect_oii_slope_change`.\n"
        "6. If Lyα is claimed, check for Lyα forest.\n"
        "7. Output verdicts for every matrix row → JSON block.\n"
    )
