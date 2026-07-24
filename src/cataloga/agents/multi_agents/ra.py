"""Catastrophe Diagnostician — Independent Root-Cause Analysis.

Two repeat observations disagree on redshift.  Diagnose WHY.

Output: ``{OUTPUT_DIR}/{targetid}/ra_verdict.json``
"""

import os
import json
from pathlib import Path

from cataloga.agents.common.base_agent import BaseAgent
from cataloga.harness.tools import build_dual_tools

SKILL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "skills"


class ResultAuditorAgent(BaseAgent):
    """Independent catastrophe diagnostician.

    Sees both spectra, both redrock results, both FA catalogs.
    Does NOT see the HS verdict.
    """

    agent_name = "RA"
    _SKILL_DIR = SKILL_DIR
    _skill_file = "RA_skill.md"

    def build_user_message(self, coadd_path_a, coadd_path_b, targetid,
                           redrock_a, redrock_b, fa_catalog_a, fa_catalog_b,
                           peaks_a=None, troughs_a=None, peaks_b=None, troughs_b=None):
        lines = []

        # ── The catastrophe ──
        za = redrock_a.get('z', 0); zb = redrock_b.get('z', 0)
        dz = abs(za - zb)
        dv = 299792.458 * dz / (1 + min(za, zb))
        lines.append(f"## Redshift Catastrophe: TARGETID {targetid}\n")
        lines.append(f"This target was observed TWICE. The two redrock fits disagree catastrophically:\n")
        lines.append(f"|  | Observation A | Observation B |")
        lines.append(f"|--|---------------|---------------|")
        lines.append(f"| FITS | `{coadd_path_a}` | `{coadd_path_b}` |")
        lines.append(f"| Redshift | z = {za:.4f} | z = {zb:.4f} |")
        lines.append(f"| ZWARN | {redrock_a.get('zwarn','?')} | {redrock_b.get('zwarn','?')} |")
        lines.append(f"| SPECTYPE | {redrock_a.get('spectype','?')} | {redrock_b.get('spectype','?')} |")
        lines.append(f"| DELTACHI2 | {redrock_a.get('deltachi2',0):.0f} | {redrock_b.get('deltachi2',0):.0f} |")
        lines.append(f"\n|Δz| = {dz:.4f}  (Δv ≈ {dv:.0f} km/s)\n")

        lines.append("**Your job: diagnose WHY these two fits disagree.** "
                     "Use `read_spec(spec, wl_min, wl_max)` with `spec=\"A\"` or `\"B\"` "
                     "to examine both spectra. Use `grep_kb` for physics rules.\n")

        # ── FA catalogs ──
        for label, cat, spec_label in [("H1 (from obs A)", fa_catalog_a, "A"),
                                        ("H2 (from obs B)", fa_catalog_b, "B")]:
            lines.append(f"\n## FA-Cleaned Features: {label} (spectrum {spec_label})\n")
            feats = cat.get("features", []) if isinstance(cat, dict) else []
            keeps = [f for f in feats if f.get('recommendation') == 'KEEP']
            flags = [f for f in feats if f.get('recommendation') == 'FLAG']
            removes = [f for f in feats if f.get('recommendation') == 'REMOVE']
            lines.append(f"- KEEP: {len(keeps)}  FLAG: {len(flags)}  REMOVE: {len(removes)}")
            for f in keeps + flags:
                lines.append(f"  - {f.get('claimed_line','?')} @ {f.get('wl_obs','?'):.1f} Å  [{f.get('recommendation')}]  conf={f.get('confidence','?')}")
            if not keeps and not flags:
                lines.append("  (no surviving features)")

        # ── CWT features ──
        for label_spec, label_peaks, peaks, troughs in [
            ("A", "CWT-A", peaks_a, troughs_a),
            ("B", "CWT-B", peaks_b, troughs_b),
        ]:
            if peaks or troughs:
                lines.append(f"\n## CWT Features (spectrum {label_spec})\n")
                for l, feats in [("Emission", peaks or []), ("Absorption", troughs or [])]:
                    if feats:
                        for f in feats[:12]:
                            lines.append(f"- {'em' if l == 'Emission' else 'abs'} @ {f.get('wavelength',0):.1f} Å  SNR={f.get('snr','?'):.1f}  FWHM={f.get('FWHM_A','?'):.1f} Å")

        lines.append("\n## Instructions\n")
        lines.append("1. Survey: what are the two redshifts? What features survive FA?\n")
        lines.append("2. Core questions:\n")
        lines.append("   - Does H1 have credible features? Read them on spec A.\n")
        lines.append("   - Does H2 have credible features? Read them on spec B.\n")
        lines.append("   - What caused the wrong answer? (sky confusion, template mismatch, noise overfitting, arm boundary, etc.)\n")
        lines.append("3. Read BOTH spectra at key diagnostic wavelengths.\n")
        lines.append("4. Output: free-text diagnosis + JSON with `verdict`, `catastrophe_type`, `winning_lines`, `key_evidence`.\n")

        return "\n".join(lines)

    async def run(self, coadd_path_a, coadd_path_b, targetid,
                  redrock_a, redrock_b, fa_catalog_a, fa_catalog_b, *,
                  wl_a=None, fl_a=None, wl_b=None, fl_b=None,
                  peaks_a=None, troughs_a=None, peaks_b=None, troughs_b=None,
                  hs_verdict=None, max_turns=30, parse_json=True):
        out_dir = os.path.join(self.config.output_dir, str(targetid))
        os.makedirs(out_dir, exist_ok=True)
        stream_path = os.path.join(out_dir, "ra_react.md")
        report_path = os.path.join(out_dir, "ra_verdict.json")

        tools = build_dual_tools(wl_a, fl_a, wl_b, fl_b)
        skill = self.load_skill()
        user_msg = self.build_user_message(
            coadd_path_a, coadd_path_b, targetid,
            redrock_a, redrock_b, fa_catalog_a, fa_catalog_b,
            peaks_a, troughs_a, peaks_b, troughs_b)

        result = await self.run_with_tools(user_msg, tools, system_prompt=skill,
                                           max_turns=max_turns, parse_json=parse_json,
                                           log_prefix="RA", stream_path=stream_path)

        from cataloga.agents.common.base_agent import _extract_json_block
        result_data = result.get("result", {})
        parsed = _extract_json_block(result_data)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(parsed or result_data, f, indent=2, ensure_ascii=False, default=str)
        return result
