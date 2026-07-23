"""Pipeline runner — VI → SH×2 → FA → HS → RA.

Usage::

    from cataloga.core.config import Config
    from cataloga.tools.inputs import load_target
    from cataloga.pipeline import PipelineRunner

    config = Config()
    ti = load_target(config.input_dir, 39628250216924756)
    runner = PipelineRunner(config)
    result = await runner.run(ti)
"""

import asyncio
import csv
import logging
import os
import time

from cataloga.core.config import Config
from cataloga.tools.inputs import TargetInput
from cataloga.tools.vi import run_vi

logger = logging.getLogger(__name__)


class PipelineRunner:
    """Run the full catastrophe-detection pipeline on one target."""

    def __init__(self, config: Config):
        self.config = config

    async def run(self, ti: TargetInput) -> dict:
        """Run VI → SH×2 → FA → HS → RA.

        Uses the B-side coadd as the reference spectrum (typically the
        higher-quality observation).  Both redrock files are loaded as
        competing hypotheses.
        """
        t0 = time.time()
        tid = ti.targetid
        log = logger.info if logger.isEnabledFor(logging.INFO) else print

        log(f"\n{'='*60}")
        log(f"Pipeline: TARGETID {tid}")
        log(f"  coadd:  {ti.coadd_b}")
        log(f"  redrock A: {ti.redrock_a}")
        log(f"  redrock B: {ti.redrock_b}")

        # ── VI ─────────────────────────────────────────────────
        log("VI: loading spectrum + CWT ...")
        vi = run_vi(ti.coadd_b, ti.redrock_a, ti.redrock_b, tid,
                    cwt_snr_thresh=self.config.cwt_snr_thresh,
                    cwt_min_ridge_length=self.config.cwt_min_ridge_length,
                    cwt_n_scales=self.config.cwt_n_scales,
                    cwt_min_width=self.config.cwt_min_width,
                    cwt_max_width=self.config.cwt_max_width)
        log(f"  {len(vi['wl'])} px, {len(vi['peaks'])} peaks, "
            f"{len(vi['troughs'])} troughs")
        log(f"  H1 z={vi['redrock_a']['z']:.4f} ({vi['redrock_a']['spectype']})")
        log(f"  H2 z={vi['redrock_b']['z']:.4f} ({vi['redrock_b']['spectype']})")

        # ── Plot: CWT overview ────────────────────────────────
        from cataloga.tools.plotting import plot_cwt_overview, plot_hypothesis_lines
        out_dir = os.path.join(self.config.output_dir, str(tid))
        plot_cwt_overview(vi["wl"], vi["fl"], vi["peaks"], vi["troughs"],
                          os.path.join(out_dir, "cwt_features.png"))

        # ── SH × 2 (parallel) ──────────────────────────────────
        from cataloga.agents.multi_agents.sh import SingleHypothesisAgent
        sh = SingleHypothesisAgent(self.config)

        log("SH: evaluating H1 + H2 in parallel ...")
        sh_h1, sh_h2 = await asyncio.gather(
            sh.run(
                redshift=vi["redrock_a"]["z"],
                coadd_path=ti.coadd_b, targetid=tid,
                label="H1",
                peaks=vi["peaks"], troughs=vi["troughs"],
                masked_regions=vi["masked_regions"],
            ),
            sh.run(
                redshift=vi["redrock_b"]["z"],
                coadd_path=ti.coadd_b, targetid=tid,
                label="H2",
                peaks=vi["peaks"], troughs=vi["troughs"],
                masked_regions=vi["masked_regions"],
            ),
        )
        log(f"  SH-H1: {_tool_summary(sh_h1)}")
        log(f"  SH-H2: {_tool_summary(sh_h2)}")

        # ── Build FA input from SH CSV files ────────────────────
        out_dir = os.path.join(self.config.output_dir, str(tid))
        cat_h1 = _read_sh_csv(os.path.join(out_dir, "sh_lines_H1.csv"),
                              hypothesis_idx=0, z=vi["redrock_a"]["z"],
                              spectype=vi["redrock_a"]["spectype"])
        cat_h2 = _read_sh_csv(os.path.join(out_dir, "sh_lines_H2.csv"),
                              hypothesis_idx=1, z=vi["redrock_b"]["z"],
                              spectype=vi["redrock_b"]["spectype"])

        # ── FA ─────────────────────────────────────────────────
        from cataloga.agents.multi_agents.fa import FeatureAuditorAgent
        fa = FeatureAuditorAgent(self.config)

        log("FA: cross-hypothesis audit ...")
        fa_result = await fa.run(
            coadd_path=ti.coadd_b, targetid=tid,
            line_catalogs=[cat_h1, cat_h2],
        )
        log(f"  FA: {_tool_summary(fa_result)}")

        # ── Plot: per-hypothesis lines ────────────────────────
        for label in ("H1", "H2"):
            plot_hypothesis_lines(vi["wl"], vi["fl"],
                                  os.path.join(out_dir, f"sh_lines_{label}.csv"),
                                  os.path.join(out_dir, f"fa_cleaned_{label}.png"),
                                  label=label)

        # ── Build FA result as structured catalogs ─────────────
        # FA outputs a unified verdict.  For HS, we construct
        # per-hypothesis catalogs from the FA raw output.
        fa_raw = fa_result.get("result", {})
        fa_h1 = _wrap_fa_catalog(fa_raw, hypothesis_idx=0, label="H1",
                                 z=vi["redrock_a"]["z"],
                                 spectype=vi["redrock_a"]["spectype"],
                                 sh_csv_path=os.path.join(out_dir, "sh_lines_H1.csv"))
        fa_h2 = _wrap_fa_catalog(fa_raw, hypothesis_idx=1, label="H2",
                                 z=vi["redrock_b"]["z"],
                                 spectype=vi["redrock_b"]["spectype"],
                                 sh_csv_path=os.path.join(out_dir, "sh_lines_H2.csv"))

        # ── HS ─────────────────────────────────────────────────
        from cataloga.agents.multi_agents.hs import HypothesisSynthesisAgent
        hs = HypothesisSynthesisAgent(self.config)

        log("HS: synthesis ...")
        hs_result = await hs.run(
            coadd_path=ti.coadd_b, targetid=tid,
            redrock_a=vi["redrock_a"], redrock_b=vi["redrock_b"],
            fa_catalog_a=fa_h1, fa_catalog_b=fa_h2,
        )
        hs_verdict = hs_result.get("result", {})
        if isinstance(hs_verdict, dict):
            log(f"  HS verdict: {hs_verdict.get('verdict', '?')}")
        else:
            log(f"  HS raw: {str(hs_verdict)[:200]}")

        # ── RA ─────────────────────────────────────────────────
        from cataloga.agents.multi_agents.ra import ResultAuditorAgent
        ra = ResultAuditorAgent(self.config)

        log("RA: independent review ...")
        ra_result = await ra.run(
            coadd_path=ti.coadd_b, targetid=tid,
            redrock_a=vi["redrock_a"], redrock_b=vi["redrock_b"],
            fa_catalog_a=fa_h1, fa_catalog_b=fa_h2,
            peaks=vi["peaks"], troughs=vi["troughs"],
            hs_verdict=hs_verdict if isinstance(hs_verdict, dict) else None,
        )
        ra_verdict = ra_result.get("result", {})
        if isinstance(ra_verdict, dict):
            log(f"  RA verdict: {ra_verdict.get('verdict', '?')} "
                f"({ra_verdict.get('calibrated_confidence', '?')})")

        elapsed = time.time() - t0
        log(f"\nPipeline done in {elapsed:.0f}s")
        log(f"Output: {self.config.output_dir}/{tid}/")

        return {
            "targetid": tid,
            "vi": {k: vi[k] for k in ["peaks", "troughs", "masked_regions"]},
            "vi_peaks": len(vi["peaks"]), "vi_troughs": len(vi["troughs"]),
            "sh_h1": sh_h1, "sh_h2": sh_h2,
            "fa": fa_result,
            "hs": hs_result, "ra": ra_result,
            "elapsed_s": round(elapsed, 1),
        }


def _wrap_fa_catalog(fa_result, *, hypothesis_idx, label, z, spectype,
                     sh_csv_path: str = ""):
    """Wrap FA result in the dict structure HS expects.

    Cross-references FA feature_verdicts (indexed by wavelength) with the
    SH line CSV to recover line names.
    """
    features = []
    n_keep = n_flag = n_remove = 0
    removed = []

    # Build wavelength→name lookup from SH CSV
    wl_to_name = {}
    if sh_csv_path and os.path.exists(sh_csv_path):
        with open(sh_csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    obs = float(row.get("predicted_obs", 0))
                except (ValueError, TypeError):
                    continue
                name = row.get("name", "?")
                if obs > 0:
                    wl_to_name[obs] = name

    def _match_name(wl: float) -> str:
        """Find the closest SH line name within 5 Å of *wl*."""
        best = None
        best_dist = 999
        for csv_wl, csv_name in wl_to_name.items():
            d = abs(csv_wl - wl)
            if d < 5.0 and d < best_dist:
                best = csv_name
                best_dist = d
        return best or "?"

    if isinstance(fa_result, dict):
        lines = (fa_result.get("feature_verdicts", [])
                 or fa_result.get("lines", [])
                 or fa_result.get("features", []))
        for ln in lines:
            verdict = ln.get("recommendation", ln.get("verdict", ln.get("fa_verdict", "?")))
            wl = ln.get("wl_obs", ln.get("obs_wl", 0))
            name = ln.get("name") or ln.get("claimed_line") or _match_name(wl)

            if verdict == "KEEP":
                n_keep += 1
            elif verdict == "FLAG":
                n_flag += 1
            else:
                n_remove += 1
                removed.append(name)

            features.append({
                "wl_obs": wl,
                "feature_type": ln.get("feature_type", ln.get("type", "emission")),
                "claimed_line": name,
                "sh_status": ln.get("status", ln.get("sh_status", "?")),
                "recommendation": verdict,
                "confidence": ln.get("confidence", "?"),
            })
    else:
        features.append({
            "wl_obs": 0, "feature_type": "emission",
            "claimed_line": "(see FA raw output below)",
            "sh_status": "?", "recommendation": "SEE_RAW", "confidence": "?",
        })

    return {
        "hypothesis_idx": hypothesis_idx,
        "label": label, "z": z, "spectype": spectype,
        "features": features,
        "n_keep": n_keep, "n_flag": n_flag, "n_remove": n_remove,
        "removed": removed,
        "_raw": str(fa_result)[:10000],
    }


def _tool_summary(result: dict) -> str:
    """One-line summary of an agent's tool calls."""
    tools = result.get("tool_results", [])
    if not tools:
        return "(no tool calls)"
    names = [t["name"] for t in tools]
    return f"{len(tools)} calls: {', '.join(names)}"


def _safe_float(val, default=0.0):
    """Parse float, returning *default* for non-numeric placeholders like '—'."""
    if val is None:
        return default
    s = str(val).strip()
    if not s or s in ("—", "-", "N/A", "nan", "NaN"):
        return default
    try:
        return float(s)
    except (ValueError, TypeError):
        return default


def _read_sh_csv(csv_path: str, hypothesis_idx: int, z: float,
                 spectype: str = "?") -> dict:
    """Read an SH line CSV into the dict format FA's ``build_user_message`` expects."""
    if not os.path.exists(csv_path):
        return {
            "hypothesis_idx": hypothesis_idx, "z": z,
            "label": f"H{hypothesis_idx + 1}",
            "spectype": spectype, "n_likely": 0, "n_marginal": 0,
            "lines": [],
        }

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        lines = []
        n_likely, n_marginal = 0, 0
        for row in reader:
            status = row.get("status", "?")
            if status == "LIKELY":
                n_likely += 1
            elif status == "MARGINAL":
                n_marginal += 1

            name = row.get("name", "?")
            line = {
                "name": name,
                "rest_wl": _safe_float(row.get("rest_wavelength", 0)),
                "obs_wl": _safe_float(row.get("predicted_obs", 0)),
                "status": status,
                "type": "absorption" if name.endswith("_abs") else "emission",
                "width_class": "narrow",
            }
            fc = row.get("fitted_center", "")
            if fc and fc.strip() and fc.strip() not in ("—", "-", "N/A"):
                try:
                    line["fitted_center"] = float(fc)
                    line["fwhm_km_s"] = _safe_float(row.get("fwhm_km_s"))
                    line["local_snr"] = _safe_float(row.get("cwt_snr"))
                except (ValueError, TypeError):
                    pass
            lines.append(line)

    return {
        "hypothesis_idx": hypothesis_idx, "z": z,
        "label": f"H{hypothesis_idx + 1}",
        "spectype": spectype,
        "n_likely": n_likely, "n_marginal": n_marginal,
        "lines": lines,
    }
