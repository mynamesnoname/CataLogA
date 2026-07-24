"""Hypothesis Synthesis Agent.

Cross-compares two FA-audited line catalogs and produces a verdict
(PREFER_H1 / PREFER_H2 / INDETERMINATE) with a narrative assessment.

Adapted from FORMA's ``harness/hypothesis_synthesis.py`` for CataLogA's
repeat-observation catastrophe detection workflow.

Key differences from FORMA:
- No per-line scoring or ranking — LLM forms a holistic qualitative impression
- No pre-defined classification taxonomy — output is narrative, not labels
- INDETERMINATE is a valid scientific verdict (not a failure)
- Side-by-side presentation of both hypotheses' FA-cleaned features
"""

import numpy as np

from cataloga.tools.spectrum import load_coadd_spectrum, merged_spectrum

# ---------------------------------------------------------------------------
# FA Cleaned Catalog Comparison Table
# ---------------------------------------------------------------------------

def _build_fa_comparison_table(catalog_a: dict, catalog_b: dict) -> str:
    """Side-by-side table of FA-cleaned features from both hypotheses.
    Only KEEP and FLAG shown (REMOVED excluded)."""

    all_features = []  # (wl, ftype, [(hyp_idx, line_name, sh_status)])

    for cat_idx, cat in enumerate([catalog_a, catalog_b]):
        idx = cat["hypothesis_idx"]
        for f in cat.get("features", []):
            if f.get("recommendation") not in ("KEEP", "FLAG"):
                continue  # REMOVED features are summarized in the section below
            wl = round(f["wl_obs"], 1)
            ftype = f.get("feature_type", "emission")
            found = False
            for row in all_features:
                if abs(row[0] - wl) < 2.0 and row[1] == ftype:
                    row[2].append((idx, f["claimed_line"], f.get("sh_status", "?")))
                    found = True
                    break
            if not found:
                all_features.append((wl, ftype, [(idx, f["claimed_line"], f.get("sh_status", "?"))]))

    if not all_features:
        return "\n## FA Cleaned Features\n\n(No features survived FA audit — all REMOVED.)\n"

    all_features.sort(key=lambda x: x[0])

    lines = [
        "## FA Cleaned Feature Catalogs (Side by Side)\n",
        "Only KEEP/FLAG shown. REMOVED features in the section below.",
        "",
        "| λ_obs (Å) | Type | H1 Claim | H1 SH | H2 Claim | H2 SH | FA Verdict | Confidence |",
        "|-----------|------|----------|-------|----------|-------|------------|------------|",
    ]

    for wl, ftype, claims in all_features:
        h1_claim = "—"; h1_status = "—"
        h2_claim = "—"; h2_status = "—"
        fa_verdict = "?"; fa_confidence = "?"
        for hyp_idx, name, status in claims:
            if hyp_idx == 0:
                h1_claim = name; h1_status = status
            else:
                h2_claim = name; h2_status = status
        for cat in [catalog_a, catalog_b]:
            for f in cat.get("features", []):
                if abs(f["wl_obs"] - wl) < 2.0:
                    fa_verdict = f.get("recommendation", "?")
                    fa_confidence = f.get("confidence", "?")
                    break

        v = "✓KEEP" if fa_verdict == "KEEP" else "⚑FLAG" if fa_verdict == "FLAG" else fa_verdict
        lines.append(
            f"| {wl:.1f} | {ftype} | {h1_claim} | {h1_status} | "
            f"{h2_claim} | {h2_status} | {v} | {fa_confidence} |"
        )

    ka = sum(1 for f in catalog_a.get("features", []) if f.get("recommendation") == "KEEP")
    fa_a = sum(1 for f in catalog_a.get("features", []) if f.get("recommendation") == "FLAG")
    kb = sum(1 for f in catalog_b.get("features", []) if f.get("recommendation") == "KEEP")
    fb = sum(1 for f in catalog_b.get("features", []) if f.get("recommendation") == "FLAG")
    lines.append(f"\n**H1: {ka} KEEP + {fa_a} FLAG  |  H2: {kb} KEEP + {fb} FLAG**")
    return "\n".join(lines) + "\n"


def _build_removed_summary(catalog_a: dict, catalog_b: dict) -> str:
    """Summarize FA-REMOVED features per hypothesis."""
    lines = ["## FA-REMOVED Features\n"]
    for cat in [catalog_a, catalog_b]:
        label = cat["label"]
        removed = cat.get("features_removed", [])
        if removed:
            lines.append(f"### {label} — {len(removed)} removed")
            for f in removed:
                reason = f.get("reason", "")
                lines.append(
                    f"- **{f['claimed_line']}** @ {f['wl_obs']:.1f} Å "
                    f"(SH: {f.get('sh_status', '?')})" +
                    (f"  → {reason}" if reason else "")
                )
            lines.append("")
        else:
            lines.append(f"### {label}: no features removed\n")
    return "\n".join(lines) + "\n"


def _build_diagnostics_section(diagnostics: dict | None) -> str:
    if not diagnostics:
        return ""
    lines = ["## Pre-Computed Diagnostics\n"]
    for key, value in diagnostics.items():
        lines.append(f"- **{key}**: {value}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Full user message builder
# ---------------------------------------------------------------------------

def build_user_message(
    coadd_a: str,
    coadd_b: str,
    targetid: int,
    redrock_a: dict,
    redrock_b: dict,
    fa_catalog_a: dict,
    fa_catalog_b: dict,
    peaks_a=None, troughs_a=None,
    peaks_b=None, troughs_b=None,
    diagnostics: dict | None = None,
) -> str:
    """Build the HS user prompt.

    Parameters
    ----------
    coadd_path : str — coadd file path (HS can read via read_spectrum_region).
    targetid : int
    redrock_a, redrock_b : dict
        Keys: z, zerr, zwarn, spectype, deltachi2, tile, night, petal.
    fa_catalog_a, fa_catalog_b : dict
        - hypothesis_idx: 0 (H1) or 1 (H2)
        - label: "z=... SPTYPE (expX)"
        - features: list[dict] — KEEP/FLAG with wl_obs, feature_type, claimed_line,
          sh_status, is_real, confidence, recommendation
        - features_removed: list[dict] — REMOVED with wl_obs, claimed_line, sh_status, reason
    diagnostics : dict, optional — Lyα forest, O II slope-change, doublet results.
    """
    # ---- Spectrum summary ----
    sp = load_coadd_spectrum(coadd_b, targetid)
    w_all, f_all, iv_all = merged_spectrum(sp)
    wl_min = float(np.nanmin(w_all))
    wl_max = float(np.nanmax(w_all))
    noise = 1.0 / np.sqrt(np.maximum(iv_all, 1e-30))
    valid = np.isfinite(noise) & (noise < 1e10)
    if valid.sum() > 100:
        snr_median = float(np.nanmedian(np.abs(f_all)[valid] / noise[valid]))
    else:
        snr_median = float(np.nanmedian(np.abs(f_all) / np.nanstd(f_all)))
    n_finite = int(np.sum(np.isfinite(f_all)))

    # ---- Redrock conflict summary ----
    def _rr_row(label, rr):
        return (
            f"| {label} | {rr['z']:.4f} | {rr.get('zerr', 0):.4f} | "
            f"{rr.get('zwarn', '?')} | {rr.get('spectype', '?')} | "
            f"{rr.get('deltachi2', 0):.0f} | "
            f"({rr.get('tile','?')},{rr.get('night','?')},{rr.get('petal','?')}) |"
        )

    dz = abs(redrock_a["z"] - redrock_b["z"])
    z_min = min(redrock_a["z"], redrock_b["z"])
    dv = dz / (1 + z_min) * 299792.458
    both_w0 = (redrock_a.get("zwarn", 1) == 0) and (redrock_b.get("zwarn", 1) == 0)

    redrock_table = (
        "## Redrock Summary\n\n"
        "| Exposure | z | ZERR | ZWARN | SPECTYPE | DELTACHI2 | (tile,night,petal) |\n"
        "|----------|----|------|-------|----------|--------|---------------------|\n"
        + _rr_row("H1 (expA)", redrock_a) + "\n"
        + _rr_row("H2 (expB)", redrock_b) + "\n\n"
        f"|Δz| = {dz:.4f} → Δv = {dv:,.0f} km/s. "
        + ("**BOTH ZWARN=0 — pipeline confident but contradictory → strict catastrophe.**"
           if both_w0 else "")
        + "\n"
    )

    # ---- Spectrum info ----
    spec_info = (
        "## Spectrum Info\n\n"
        "Two repeat observations of the same source:\n\n"
        f"| Coadd A (H1) | `{coadd_a}` |\n"
        f"| Coadd B (H2) | `{coadd_b}` |\n"
        f"| TARGETID | {targetid} |\n"
        f"| Wavelength | {wl_min:.0f} – {wl_max:.0f} Å ({n_finite} valid pixels) |\n"
        f"| Median SNR | {snr_median:.1f} |\n"
        f"| Cameras | B:3600-5800, R:5760-7620, Z:7520-9824 |\n"
        f"| ⚠ R/Z boundary | 7520-7620 Å — noisy, features here are suspect |\n"
    )

    # ---- Sections ----
    fa_table = _build_fa_comparison_table(fa_catalog_a, fa_catalog_b)
    removed = _build_removed_summary(fa_catalog_a, fa_catalog_b)
    diag = _build_diagnostics_section(diagnostics)

    # ---- Tools ----
    tools = (
        "## Tools\n\n"
        "- **`read_spectrum_region(wl_min, wl_max)`**: Inspect a raw spectrum slice.\n"
        "- **`grep_kb(pattern)`**: Search the knowledge base (skyline positions, "
        "doublet spacing, ionization rules).\n"
        "- **`write_report(file_path, content)`**: Save your narrative assessment.\n"
    )

    # ---- Task ----
    task = (
        "## Task\n\n"
        "Two redshift hypotheses exist for the **same astronomical source** "
        "(repeat observations — same TARGETID, different exposures).\n\n"
        "Follow the skill prompt:\n"
        "1. **Survey** (Phase 1): study the redrock conflict, FA survival rates, feature quality\n"
        "2. **Investigate** (Phase 2): use `read_spectrum_region` and `grep_kb` to check "
        "any suspicious features, skyline positions, R/Z boundary issues\n"
        "3. **Output** (Phase 3): free-text narrative, then JSON block\n\n"
        "**Rules**:\n"
        "- Do NOT score or rank — form a qualitative impression\n"
        "- INDETERMINATE is valid — do NOT force a preference\n"
        "- Reference specific features by name, wavelength, and measured properties\n"
    )

    return (
        spec_info + "\n"
        + redrock_table + "\n"
        + fa_table + "\n"
        + removed + "\n"
        + diag + "\n"
        + tools + "\n"
        + task
    )
