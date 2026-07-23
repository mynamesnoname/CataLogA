"""Single-Hypothesis Evaluation Agent.

Evaluates one redshift hypothesis against a DESI coadd spectrum with
LangChain agent tools (fit_peak, fit_doublet, read_spectrum_region).

Output (per targetid, per hypothesis):
  ``{OUTPUT_DIR}/{targetid}/sh_{label}.md``     — ReAct streaming log
  ``{OUTPUT_DIR}/{targetid}/sh_lines_{label}.csv`` — line catalog

Adapted from FORMA ``harness/single_hypothesis.py``.
"""

import os
from pathlib import Path

from cataloga.agents.common.base_agent import BaseAgent
from cataloga.tools.spectrum import load_coadd_spectrum, merged_spectrum
from cataloga.harness.tools import build_tools
from cataloga.agents.multi_agents._sh_prompt import (
    build_user_message as _build_user_message,
)

SKILL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "skills"


class SingleHypothesisAgent(BaseAgent):
    """Evaluate a single redshift hypothesis.

    ``run()`` creates a LangChain agent with fit_peak/fit_doublet/
    read_spectrum tools.  The LLM actively calls tools to verify each
    predicted line.
    """

    agent_name = "SH"
    _SKILL_DIR = SKILL_DIR
    _skill_file = "SH_skill.md"

    def build_user_message(
        self,
        redshift: float,
        coadd_path: str,
        targetid: int,
        peaks: list = None,
        troughs: list = None,
        fit_results: dict = None,
        report_path: str = None,
        csv_path: str = None,
        z_min: float = None,
        z_max: float = None,
        masked_regions: list = None,
    ) -> str:
        """Build the SH user prompt."""
        return _build_user_message(
            redshift, coadd_path, targetid,
            peaks or [], troughs or [],
            fit_results=fit_results,
            report_path=report_path, csv_path=csv_path,
            z_min=z_min, z_max=z_max,
            masked_regions=masked_regions,
        )

    async def run(
        self,
        redshift: float,
        coadd_path: str,
        targetid: int,
        *,
        label: str = "H",
        peaks: list = None,
        troughs: list = None,
        z_min: float = None,
        z_max: float = None,
        masked_regions: list = None,
        max_turns: int = 30,
        parse_json: bool = True,
    ) -> dict:
        """Run SH evaluation with LangChain agent tools.

        Parameters
        ----------
        label : str
            Label for this hypothesis (e.g. "H1", "H2") — used in output names.
        """
        out_dir = os.path.join(self.config.output_dir, str(targetid))
        os.makedirs(out_dir, exist_ok=True)
        report_path = os.path.join(out_dir, f"sh_{label}.md")
        csv_path = os.path.join(out_dir, f"sh_lines_{label}.csv")
        stream_path = os.path.join(out_dir, f"sh_{label}_react.md")

        spectrum = load_coadd_spectrum(coadd_path, targetid)
        wl, fl, _iv = merged_spectrum(spectrum)
        tools = build_tools(wl, fl)
        skill = self.load_skill()

        user_msg = self.build_user_message(
            redshift, coadd_path, targetid,
            peaks=peaks, troughs=troughs, fit_results=None,
            report_path=report_path, csv_path=csv_path,
            z_min=z_min, z_max=z_max, masked_regions=masked_regions,
        )

        return await self.run_with_tools(
            user_msg, tools,
            system_prompt=skill,
            max_turns=max_turns,
            parse_json=parse_json,
            log_prefix="SH",
            stream_path=stream_path,
        )
