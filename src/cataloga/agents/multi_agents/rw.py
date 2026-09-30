"""Report Writer Agent — final consolidated summary.

Runs last, after HS and RA. Reads every output file already written for one
target (SH per-hypothesis reports + line catalogs, FA verdicts, HS synthesis,
RA diagnosis) and writes one polished, human-readable report combining them.
Single-shot call (no tools) — it synthesizes already-completed analysis, it
does not re-examine the spectrum.

Output: ``{PROJECT_ROOT}/reports/{targetid}.md``
"""

import os
from pathlib import Path

from cataloga.agents.common.base_agent import BaseAgent

SKILL_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "skills"
_PROJECT_ROOT = Path(__file__).resolve().parents[4]

# (section title, filename in {OUTPUT_DIR}/{targetid}/)
_SOURCE_FILES = [
    ("SH Report — H1", "sh_H1.md"),
    ("SH Report — H2", "sh_H2.md"),
    ("SH Line Catalog — H1 (CSV)", "sh_lines_H1.csv"),
    ("SH Line Catalog — H2 (CSV)", "sh_lines_H2.csv"),
    ("FA Verdict — H1 (JSON)", "fa_H1_verdict.json"),
    ("FA Verdict — H2 (JSON)", "fa_H2_verdict.json"),
    ("HS Verdict (JSON)", "hs_verdict.json"),
    ("RA Verdict (JSON)", "ra_verdict.json"),
]


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return "(missing — this stage's output file was not found)"


class ReportWriterAgent(BaseAgent):
    """Synthesizes all upstream stage outputs into one final report."""

    agent_name = "RW"
    _SKILL_DIR = SKILL_DIR
    _skill_file = "RW_skill.md"

    def build_user_message(self, targetid, out_dir: str) -> str:
        sections = [f"# All Pipeline Outputs for TARGETID {targetid}\n"]
        for title, fname in _SOURCE_FILES:
            content = _read(os.path.join(out_dir, fname))
            sections.append(f"\n## {title}\n\n```\n{content}\n```\n")
        return "\n".join(sections)

    async def run(self, targetid, *, max_retries: int = 3, retry_delay: int = 30):
        out_dir = os.path.join(self.config.output_dir, str(targetid))
        reports_dir = os.path.join(str(_PROJECT_ROOT), "reports")
        os.makedirs(reports_dir, exist_ok=True)
        report_path = os.path.join(reports_dir, f"{targetid}.md")

        skill = self.load_skill()
        user_msg = self.build_user_message(targetid, out_dir)
        report_text, response = await self.call_llm(
            skill, user_msg, parse_json=False,
            max_retries=max_retries, retry_delay=retry_delay,
            return_raw=True,
        )

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_text)

        # "messages": [response] — matches the shape _usage_summary() expects
        # (a list of AIMessage-like objects with .response_metadata) so this
        # single-shot call's cost is counted alongside the tool-calling stages.
        return {"result": report_text, "path": report_path, "messages": [response]}
