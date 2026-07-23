"""Feature Auditor Agent.

Audits claimed features from ONE hypothesis against ONE spectrum.
Two FA sessions run in parallel (one per hypothesis), then HS synthesizes.

Output: ``{OUTPUT_DIR}/{targetid}/fa_{label}.md``
"""

import os
import json
from pathlib import Path

from cataloga.agents.common.base_agent import BaseAgent
from cataloga.harness.tools import build_tools

SKILL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "skills"

from cataloga.agents.multi_agents._fa_prompt import build_user_message as _build_user_message


class FeatureAuditorAgent(BaseAgent):
    """Audit one hypothesis's features against one spectrum."""

    agent_name = "FA"
    _SKILL_DIR = SKILL_DIR

    def build_user_message(self, coadd_path, targetid, line_catalog):
        return _build_user_message(coadd_path, targetid, [line_catalog])

    async def run(self, coadd_path, targetid, line_catalog, *,
                  wl=None, fl=None, label="H", max_turns=40, parse_json=True):
        out_dir = os.path.join(self.config.output_dir, str(targetid))
        os.makedirs(out_dir, exist_ok=True)
        stream_path = os.path.join(out_dir, f"fa_{label}_react.md")
        report_path = os.path.join(out_dir, f"fa_{label}_verdict.json")

        tools = build_tools(wl, fl)
        skill = self.load_skill()
        user_msg = self.build_user_message(coadd_path, targetid, line_catalog)

        result = await self.run_with_tools(user_msg, tools, system_prompt=skill,
                                           max_turns=max_turns, parse_json=parse_json,
                                           log_prefix=f"FA-{label}", stream_path=stream_path)

        from cataloga.agents.common.base_agent import _extract_json_block
        result_data = result.get("result", {})
        parsed = _extract_json_block(result_data)
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(parsed or result_data, f, indent=2, ensure_ascii=False, default=str)
        return result
