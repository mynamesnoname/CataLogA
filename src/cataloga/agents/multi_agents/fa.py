"""Feature Auditor Agent.

Cross-hypothesis spectrum verification.  Builds the contradiction matrix
and delegates feature reality checking to the LLM following
``data/skills/FA_skill.md``.

Output (per targetid):
  ``{OUTPUT_DIR}/{targetid}/fa.md``          — ReAct streaming log
  ``{OUTPUT_DIR}/{targetid}/fa_verdict.json``  — KEEP/FLAG/REMOVE verdicts

Adapted from FORMA ``AnalysisAuditor.py`` / ``feature_audit_skill.md``.
"""

import os
import json
from pathlib import Path

from cataloga.agents.common.base_agent import BaseAgent
from cataloga.tools.spectrum import load_coadd_spectrum, merged_spectrum
from cataloga.harness.tools import build_tools
from cataloga.agents.multi_agents._fa_prompt import build_user_message as _build_user_message

SKILL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "skills"


class FeatureAuditorAgent(BaseAgent):
    """Cross-hypothesis feature verification.

    ``run()`` creates a LangChain agent with read_spectrum_region,
    detect_oii_slope_change, grep_kb, and write_report tools.
    """

    agent_name = "FA"
    _SKILL_DIR = SKILL_DIR

    def build_user_message(
        self,
        coadd_path: str,
        targetid: int,
        line_catalogs: list[dict],
    ) -> str:
        return _build_user_message(coadd_path, targetid, line_catalogs)

    async def run(
        self,
        coadd_path: str,
        targetid: int,
        line_catalogs: list[dict],
        *,
        max_turns: int = 40,
        parse_json: bool = True,
    ) -> dict:
        """Run Feature Auditor with LangChain agent tools."""
        out_dir = os.path.join(self.config.output_dir, str(targetid))
        os.makedirs(out_dir, exist_ok=True)
        stream_path = os.path.join(out_dir, "fa_react.md")
        report_path = os.path.join(out_dir, "fa_verdict.json")

        spectrum = load_coadd_spectrum(coadd_path, targetid)
        wl, fl, _iv = merged_spectrum(spectrum)

        all_tools = build_tools(wl, fl)
        fa_tool_names = {"_read_spectrum_region", "_detect_oii_slope_change",
                         "grep_kb", "write_report"}
        tools = [t for t in all_tools if t.__name__ in fa_tool_names]

        skill = self.load_skill()
        user_msg = self.build_user_message(coadd_path, targetid, line_catalogs)

        result = await self.run_with_tools(
            user_msg, tools,
            system_prompt=skill,
            max_turns=max_turns,
            parse_json=parse_json,
            log_prefix="FA",
            stream_path=stream_path,
        )

        # Save FA verdict JSON
        import json
        from cataloga.agents.common.base_agent import _extract_json_block
        result_data = result.get("result", {})
        parsed = _extract_json_block(result_data)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(parsed or result_data, f, indent=2, ensure_ascii=False, default=str)

        return result
