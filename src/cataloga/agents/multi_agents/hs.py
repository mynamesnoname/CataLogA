"""Hypothesis Synthesis Agent.

Cross-compares two FA-audited line catalogs with dual-spectrum access.

Output: ``{OUTPUT_DIR}/{targetid}/hs_verdict.json``
"""

import os
import json
from pathlib import Path

from cataloga.agents.common.base_agent import BaseAgent
from cataloga.harness.tools import build_dual_tools, scope_tools

SKILL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "skills"

# HS_synthesis_skill.md only ever documents these two — build_dual_tools()
# also includes _detect_oii/write_report, which HS must not have.
_HS_TOOL_NAMES = {"_read_spec", "grep_kb"}


class HypothesisSynthesisAgent(BaseAgent):
    """Cross-hypothesis comparison with dual-spectrum access."""

    agent_name = "HS"
    _SKILL_DIR = SKILL_DIR
    _skill_file = "HS_synthesis_skill.md"

    async def run(self, coadd_path_a, coadd_path_b, targetid,
                  redrock_a, redrock_b, fa_catalog_a, fa_catalog_b, *,
                  wl_a=None, fl_a=None, wl_b=None, fl_b=None,
                  peaks_a=None, troughs_a=None, peaks_b=None, troughs_b=None,
                  diagnostics=None, max_turns=40, parse_json=True):
        from cataloga.agents.multi_agents._hs_prompt import build_user_message as _build

        out_dir = os.path.join(self.config.output_dir, str(targetid))
        os.makedirs(out_dir, exist_ok=True)
        stream_path = os.path.join(out_dir, "hs_react.md")
        report_path = os.path.join(out_dir, "hs_verdict.json")

        tools = scope_tools(build_dual_tools(wl_a, fl_a, wl_b, fl_b), _HS_TOOL_NAMES)
        skill = self.load_skill()
        user_msg = _build(coadd_path_a, coadd_path_b, targetid,
                          redrock_a, redrock_b, fa_catalog_a, fa_catalog_b,
                          peaks_a=peaks_a, troughs_a=troughs_a,
                          peaks_b=peaks_b, troughs_b=troughs_b,
                          diagnostics=diagnostics)

        result = await self.run_with_tools(user_msg, tools, system_prompt=skill,
                                           max_turns=max_turns, parse_json=parse_json,
                                           log_prefix="HS", stream_path=stream_path)

        from cataloga.agents.common.base_agent import _extract_json_block
        result_data = result.get("result", {})
        parsed = _extract_json_block(result_data)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(parsed or result_data, f, indent=2, ensure_ascii=False, default=str)
        return result
