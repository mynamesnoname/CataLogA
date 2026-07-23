"""Result Auditor — Independent Defensive Review.

Blind-audits the HS verdict: receives FA cleaned catalogs, redrock
summaries, and spectrum access — but NOT the HS conclusion itself.

Output (per targetid):
  ``{OUTPUT_DIR}/{targetid}/ra_react.md``      — ReAct streaming log
  ``{OUTPUT_DIR}/{targetid}/ra_verdict.json``    — CONFIRM/NEEDS_REVISION/UNCERTAIN

Adapted from FORMA ``AnalysisAuditor.py`` (Stage B) / ``result_auditor_skill.md``.
"""

import os
import json
from pathlib import Path

from cataloga.agents.common.base_agent import BaseAgent
from cataloga.tools.spectrum import load_coadd_spectrum, merged_spectrum
from cataloga.harness.tools import build_tools

SKILL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "skills"


class ResultAuditorAgent(BaseAgent):
    """Independent defensive review of the HS verdict.

    ``run()`` creates a LangChain agent with read_spectrum_region and
    grep_kb tools.  RA does NOT see the HS conclusion — it audits the
    FA catalogs and redrock summaries independently.
    """

    agent_name = "RA"
    _SKILL_DIR = SKILL_DIR
    _skill_file = "RA_skill.md"

    def build_user_message(
        self,
        coadd_path: str,
        targetid: int,
        redrock_a: dict,
        redrock_b: dict,
        fa_catalog_a: dict,
        fa_catalog_b: dict,
        peaks: list = None,
        troughs: list = None,
        hs_verdict: dict | None = None,
    ) -> str:
        """Build the RA user prompt.

        *hs_verdict* is optional — when provided, RA can cross-check but
        should still form its own independent judgment.
        """
        lines = []

        # ── Spectrum context ──────────────────────────────────
        lines.append("## Spectrum")
        lines.append(f"- Coadd: `{coadd_path}`")
        lines.append(f"- TARGETID: {targetid}")

        # ── Redrock summaries ─────────────────────────────────
        lines.append("\n## Redrock Hypotheses\n")
        for label, rr in [("H1 (A)", redrock_a), ("H2 (B)", redrock_b)]:
            lines.append(
                f"- **{label}**: z={rr.get('z', '?'):.4f}  "
                f"type={rr.get('spectype', '?')}  "
                f"ZWARN={rr.get('zwarn', '?')}  "
                f"chi2={rr.get('chi2', '?'):.0f}"
            )

        # ── FA catalogs ───────────────────────────────────────
        lines.append("\n## FA Cleaned Catalogs\n")
        for label, cat in [("H1", fa_catalog_a), ("H2", fa_catalog_b)]:
            lines.append(f"### {label}\n")
            if isinstance(cat, dict) and "lines" in cat:
                for ln in cat["lines"]:
                    lines.append(
                        f"- {ln.get('name', '?')}  "
                        f"λ_obs={ln.get('obs_wl', '?'):.1f} Å  "
                        f"verdict={ln.get('verdict', ln.get('status', '?'))}  "
                        f"SNR={ln.get('snr', ln.get('local_snr', '?'))}"
                    )
            elif isinstance(cat, list):
                for ln in cat:
                    lines.append(
                        f"- {ln.get('name', '?')}  "
                        f"λ_obs={ln.get('obs_wl', '?'):.1f} Å  "
                        f"status={ln.get('status', '?')}"
                    )
            else:
                lines.append(f"(raw: {json.dumps(cat, default=str)[:500]})")

        # ── CWT features ──────────────────────────────────────
        if peaks or troughs:
            lines.append("\n## CWT Detected Features\n")
            for label, feats in [("Emission", peaks or []), ("Absorption", troughs or [])]:
                if feats:
                    lines.append(f"### {label}\n")
                    for f in feats[:20]:
                        lines.append(
                            f"- λ={f.get('wavelength', 0):.1f} Å  "
                            f"SNR={f.get('snr', '?'):.1f}  "
                            f"FWHM={f.get('FWHM_A', '?'):.1f} Å"
                        )

        # ── HS verdict (optional, for cross-check) ────────────
        if hs_verdict:
            lines.append("\n## HS Verdict (for cross-check only — form your own)")
            lines.append(f"- Verdict: {hs_verdict.get('verdict', '?')}")
            lines.append(f"- Reasoning: {str(hs_verdict.get('reasoning', ''))[:500]}")

        # ── Instructions ──────────────────────────────────────
        lines.append("\n## Instructions\n")
        lines.append(
            "1. Review the two redrock hypotheses and FA catalogs.\n"
            "2. Apply Layer 1 physical sanity screening (no spectrum reads).\n"
            "3. Flag suspicious lines → Layer 2: `read_spectrum_region` "
            "and `grep_kb`.\n"
            "4. Form your own independent verdict.\n"
            "5. Output JSON with `verdict`, `calibrated_confidence`, "
            "`confirmed_lines`, `line_revisions`, `spectrum_issues`."
        )

        return "\n".join(lines)

    async def run(
        self,
        coadd_path: str,
        targetid: int,
        redrock_a: dict,
        redrock_b: dict,
        fa_catalog_a: dict,
        fa_catalog_b: dict,
        *,
        peaks: list = None,
        troughs: list = None,
        hs_verdict: dict | None = None,
        max_turns: int = 30,
        parse_json: bool = True,
    ) -> dict:
        """Run Result Auditor with LangChain agent tools."""
        out_dir = os.path.join(self.config.output_dir, str(targetid))
        os.makedirs(out_dir, exist_ok=True)
        stream_path = os.path.join(out_dir, "ra_react.md")
        report_path = os.path.join(out_dir, "ra_verdict.json")

        spectrum = load_coadd_spectrum(coadd_path, targetid)
        wl, fl, _iv = merged_spectrum(spectrum)

        all_tools = build_tools(wl, fl)
        ra_tool_names = {"_read_spectrum_region", "grep_kb"}
        tools = [t for t in all_tools if t.__name__ in ra_tool_names]

        skill = self.load_skill()
        user_msg = self.build_user_message(
            coadd_path, targetid, redrock_a, redrock_b,
            fa_catalog_a, fa_catalog_b,
            peaks=peaks, troughs=troughs, hs_verdict=hs_verdict,
        )

        result = await self.run_with_tools(
            user_msg, tools,
            system_prompt=skill,
            max_turns=max_turns,
            parse_json=parse_json,
            log_prefix="RA",
            stream_path=stream_path,
        )

        from cataloga.agents.common.base_agent import _extract_json_block
        result_data = result.get("result", {})
        parsed = _extract_json_block(result_data)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(parsed or result_data, f, indent=2, ensure_ascii=False, default=str)

        return result
