"""Hypothesis Synthesis Agent.

Cross-compares two FA-audited line catalogs and produces a verdict
(PREFER_H1 / PREFER_H2 / INDETERMINATE) with a narrative assessment.

Output (per targetid):
  ``{OUTPUT_DIR}/{targetid}/hs.md``            — ReAct streaming log
  ``{OUTPUT_DIR}/{targetid}/hs_verdict.json``    — PREFER_H1/PREFER_H2/INDETERMINATE

Adapted from FORMA ``harness/hypothesis_synthesis.py``.
"""

import os
import json
from pathlib import Path

from cataloga.agents.common.base_agent import BaseAgent
from cataloga.tools.spectrum import load_coadd_spectrum, merged_spectrum
from cataloga.harness.tools import build_tools
from cataloga.agents.multi_agents._hs_prompt import build_user_message as _build_user_message

SKILL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "skills"


class HypothesisSynthesisAgent(BaseAgent):
    """Cross-hypothesis comparison and verdict.

    ``run()`` creates a LangChain agent with read_spectrum_region,
    detect_oii_slope_change, grep_kb, and write_report tools.
    """

    agent_name = "HS"
    _SKILL_DIR = SKILL_DIR
    _skill_file = "HS_synthesis_skill.md"

    def build_user_message(
        self,
        coadd_path: str,
        targetid: int,
        redrock_a: dict,
        redrock_b: dict,
        fa_catalog_a: dict,
        fa_catalog_b: dict,
        diagnostics: dict | None = None,
    ) -> str:
        return _build_user_message(
            coadd_path, targetid, redrock_a, redrock_b,
            fa_catalog_a, fa_catalog_b, diagnostics,
        )

    async def run(
        self,
        coadd_path: str,
        targetid: int,
        redrock_a: dict,
        redrock_b: dict,
        fa_catalog_a: dict,
        fa_catalog_b: dict,
        *,
        diagnostics: dict | None = None,
        max_turns: int = 40,
        parse_json: bool = True,
    ) -> dict:
        """Run Hypothesis Synthesis with LangChain agent tools."""
        out_dir = os.path.join(self.config.output_dir, str(targetid))
        os.makedirs(out_dir, exist_ok=True)
        stream_path = os.path.join(out_dir, "hs_react.md")
        report_path = os.path.join(out_dir, "hs_verdict.json")

        spectrum = load_coadd_spectrum(coadd_path, targetid)
        wl, fl, _iv = merged_spectrum(spectrum)

        all_tools = build_tools(wl, fl)
        hs_tool_names = {"_read_spectrum_region", "_detect_oii_slope_change",
                         "grep_kb", "write_report"}
        tools = [t for t in all_tools if t.__name__ in hs_tool_names]

        skill = self.load_skill()
        user_msg = self.build_user_message(
            coadd_path, targetid, redrock_a, redrock_b,
            fa_catalog_a, fa_catalog_b, diagnostics,
        )

        result = await self.run_with_tools(
            user_msg, tools,
            system_prompt=skill,
            max_turns=max_turns,
            parse_json=parse_json,
            log_prefix="HS",
            stream_path=stream_path,
        )

        # Save HS verdict JSON — try to extract from markdown
        import json
        from cataloga.agents.common.base_agent import _extract_json_block
        result_data = result.get("result", {})
        parsed = _extract_json_block(result_data)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(parsed or result_data, f, indent=2, ensure_ascii=False, default=str)

        return result
