"""Pipeline runner — VI_A || VI_B → SH_H1(coadd-A) || SH_H2(coadd-B) → FA → HS → RA.

Each hypothesis is verified on the spectrum that produced it.

Usage::

    from cataloga.core.config import Config
    from cataloga.tools.inputs import load_target
    from cataloga.pipeline import PipelineRunner

    config = Config()
    ti = load_target(config.intermediate_dir, 39628250216924756)
    runner = PipelineRunner(config)
    result = await runner.run(ti)
"""

import asyncio
import csv
import logging
import os
import time

import numpy as np

from cataloga.harness.tools import build_tools, build_dual_tools

logger = logging.getLogger(__name__)


def _tool_summary(result: dict) -> str:
    tools = result.get("tool_results", [])
    if not tools:
        return "(no tool calls)"
    names = [t["name"] for t in tools]
    return f"{len(tools)} calls: {', '.join(names)}"


def _safe_float(val, default=0.0):
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
    """Read an SH line CSV into the dict format FA expects."""
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


def _wrap_fa_catalog(fa_result, *, hypothesis_idx, label, z, spectype,
                     sh_csv_path: str = ""):
    """Wrap FA result in the dict structure HS expects."""
    features = []
    n_keep = n_flag = n_remove = 0
    removed = []
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
        best, best_dist = None, 999
        for csv_wl, csv_name in wl_to_name.items():
            d = abs(csv_wl - wl)
            if d < 5.0 and d < best_dist:
                best, best_dist = csv_name, d
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


class PipelineRunner:
    """Run the full catastrophe-detection pipeline on one target."""

    def __init__(self, config):
        self.config = config

    async def run(self, ti):
        t0 = time.time()
        tid = ti.targetid
        log = logger.info if logger.isEnabledFor(logging.INFO) else print
        cfg = self.config

        log(f"\n{'='*60}")
        log(f"Pipeline: TARGETID {tid}")
        log(f"  coadd A: {ti.coadd_a}")
        log(f"  coadd B: {ti.coadd_b}")

        # ── VI × 2 (parallel) ──────────────────────────────────
        from cataloga.tools.vi import run_vi
        log("VI: loading both spectra + CWT ...")
        vi_a, vi_b = await asyncio.gather(
            asyncio.to_thread(run_vi, ti.coadd_a, ti.redrock_a, ti.redrock_b, tid,
                              cwt_snr_thresh=cfg.cwt_snr_thresh,
                              cwt_min_ridge_length=cfg.cwt_min_ridge_length,
                              cwt_n_scales=cfg.cwt_n_scales,
                              cwt_min_width=cfg.cwt_min_width,
                              cwt_max_width=cfg.cwt_max_width),
            asyncio.to_thread(run_vi, ti.coadd_b, ti.redrock_a, ti.redrock_b, tid,
                              cwt_snr_thresh=cfg.cwt_snr_thresh,
                              cwt_min_ridge_length=cfg.cwt_min_ridge_length,
                              cwt_n_scales=cfg.cwt_n_scales,
                              cwt_min_width=cfg.cwt_min_width,
                              cwt_max_width=cfg.cwt_max_width),
        )
        log(f"  VI-A: {len(vi_a['wl'])} px, {len(vi_a['peaks'])} peaks, {len(vi_a['troughs'])} troughs")
        log(f"  VI-B: {len(vi_b['wl'])} px, {len(vi_b['peaks'])} peaks, {len(vi_b['troughs'])} troughs")
        log(f"  H1 z={vi_a['redrock_a']['z']:.4f} ({vi_a['redrock_a']['spectype']})")
        log(f"  H2 z={vi_b['redrock_b']['z']:.4f} ({vi_b['redrock_b']['spectype']})")

        out_dir = os.path.join(cfg.output_dir, str(tid))

        # ── Plot: CWT × 2 ─────────────────────────────────────
        from cataloga.tools.plotting import plot_cwt_overview, plot_hypothesis_lines

        for label, vi_x in [("A", vi_a), ("B", vi_b)]:
            plot_cwt_overview(vi_x["wl"], vi_x["fl"],
                              np.array(vi_x.get("continuum", {}).get("flux", np.zeros_like(vi_x["fl"]))),
                              vi_x["peaks"], vi_x["troughs"],
                              os.path.join(out_dir, f"cwt_features_{label}.png"))

        # ── SH × 2 (parallel) — each on its own coadd ──────────
        from cataloga.agents.multi_agents.sh import SingleHypothesisAgent
        sh = SingleHypothesisAgent(cfg)

        log("SH: H1 on coadd-A, H2 on coadd-B (parallel) ...")
        sh_h1, sh_h2 = await asyncio.gather(
            sh.run(redshift=vi_a["redrock_a"]["z"],
                   coadd_path=ti.coadd_a, targetid=tid, label="H1",
                   peaks=vi_a["peaks"], troughs=vi_a["troughs"],
                   masked_regions=vi_a["masked_regions"],
                   max_turns=cfg.max_turns_sh),
            sh.run(redshift=vi_b["redrock_b"]["z"],
                   coadd_path=ti.coadd_b, targetid=tid, label="H2",
                   peaks=vi_b["peaks"], troughs=vi_b["troughs"],
                   masked_regions=vi_b["masked_regions"],
                   max_turns=cfg.max_turns_sh),
        )
        log(f"  SH-H1: {_tool_summary(sh_h1)}")
        log(f"  SH-H2: {_tool_summary(sh_h2)}")

        # ── Plot: per-hypothesis lines ─────────────────────────
        for label, z, vi_x, csv_file in [("H1", vi_a["redrock_a"]["z"], vi_a, "sh_lines_H1.csv"),
                                          ("H2", vi_b["redrock_b"]["z"], vi_b, "sh_lines_H2.csv")]:
            plot_hypothesis_lines(vi_x["wl"], vi_x["fl"],
                                  np.array(vi_x.get("continuum", {}).get("flux", np.zeros_like(vi_x["fl"]))),
                                  os.path.join(out_dir, csv_file),
                                  os.path.join(out_dir, f"fa_cleaned_{label}.png"),
                                  redshift=z, title=label)

        # ── Build FA input from SH CSVs ────────────────────────
        cat_h1 = _read_sh_csv(os.path.join(out_dir, "sh_lines_H1.csv"),
                              hypothesis_idx=0, z=vi_a["redrock_a"]["z"],
                              spectype=vi_a["redrock_a"]["spectype"])
        cat_h2 = _read_sh_csv(os.path.join(out_dir, "sh_lines_H2.csv"),
                              hypothesis_idx=1, z=vi_b["redrock_b"]["z"],
                              spectype=vi_b["redrock_b"]["spectype"])

        # ── FA × 2 (parallel) ──────────────────────────────────
        from cataloga.agents.multi_agents.fa import FeatureAuditorAgent
        fa = FeatureAuditorAgent(cfg)

        log("FA: auditing H1 on coadd-A, H2 on coadd-B (parallel) ...")
        fa_h1_result, fa_h2_result = await asyncio.gather(
            fa.run(ti.coadd_a, tid, cat_h1, wl=vi_a["wl"], fl=vi_a["fl"],
                   label="H1", max_turns=cfg.max_turns_fa),
            fa.run(ti.coadd_b, tid, cat_h2, wl=vi_b["wl"], fl=vi_b["fl"],
                   label="H2", max_turns=cfg.max_turns_fa),
        )
        log(f"  FA-H1: {_tool_summary(fa_h1_result)}")
        log(f"  FA-H2: {_tool_summary(fa_h2_result)}")

        # ── HS: dual-spectrum synthesis ────────────────────────
        from cataloga.agents.multi_agents.hs import HypothesisSynthesisAgent
        hs = HypothesisSynthesisAgent(cfg)

        fa_h1 = _wrap_fa_catalog(fa_h1_result.get("result", {}),
                                 hypothesis_idx=0, label="H1",
                                 z=vi_a["redrock_a"]["z"], spectype=vi_a["redrock_a"]["spectype"],
                                 sh_csv_path=os.path.join(out_dir, "sh_lines_H1.csv"))
        fa_h2 = _wrap_fa_catalog(fa_h2_result.get("result", {}),
                                 hypothesis_idx=1, label="H2",
                                 z=vi_b["redrock_b"]["z"], spectype=vi_b["redrock_b"]["spectype"],
                                 sh_csv_path=os.path.join(out_dir, "sh_lines_H2.csv"))

        log("HS: synthesis (dual-spectrum) ...")
        hs_result = await hs.run(
            coadd_path_a=ti.coadd_a, coadd_path_b=ti.coadd_b, targetid=tid,
            redrock_a=vi_a["redrock_a"], redrock_b=vi_b["redrock_b"],
            fa_catalog_a=fa_h1, fa_catalog_b=fa_h2,
            wl_a=vi_a["wl"], fl_a=vi_a["fl"],
            wl_b=vi_b["wl"], fl_b=vi_b["fl"],
            peaks_a=vi_a["peaks"], troughs_a=vi_a["troughs"],
            peaks_b=vi_b["peaks"], troughs_b=vi_b["troughs"],
            max_turns=cfg.max_turns_hs,
        )
        hs_verdict = hs_result.get("result", {})
        if isinstance(hs_verdict, dict):
            log(f"  HS verdict: {hs_verdict.get('verdict', '?')}")
        else:
            log(f"  HS raw: {str(hs_verdict)[:200]}")

        # ── RA: dual-spectrum review ───────────────────────────
        from cataloga.agents.multi_agents.ra import ResultAuditorAgent
        ra = ResultAuditorAgent(cfg)

        log("RA: independent review (dual-spectrum) ...")
        ra_result = await ra.run(
            coadd_path_a=ti.coadd_a, coadd_path_b=ti.coadd_b, targetid=tid,
            redrock_a=vi_a["redrock_a"], redrock_b=vi_b["redrock_b"],
            fa_catalog_a=fa_h1, fa_catalog_b=fa_h2,
            wl_a=vi_a["wl"], fl_a=vi_a["fl"],
            wl_b=vi_b["wl"], fl_b=vi_b["fl"],
            peaks_a=vi_a["peaks"], troughs_a=vi_a["troughs"],
            peaks_b=vi_b["peaks"], troughs_b=vi_b["troughs"],
            hs_verdict=hs_verdict if isinstance(hs_verdict, dict) else None,
            max_turns=cfg.max_turns_ra,
        )
        ra_verdict = ra_result.get("result", {})
        if isinstance(ra_verdict, dict):
            log(f"  RA verdict: {ra_verdict.get('verdict', '?')} "
                f"({ra_verdict.get('calibrated_confidence', '?')})")

        elapsed = time.time() - t0
        log(f"\nPipeline done in {elapsed:.0f}s")
        log(f"Output: {cfg.output_dir}/{tid}/")

        return {
            "targetid": tid,
            "vi_a": dict(vi_a, wl=None, fl=None, iv=None, spectrum=None, continuum=None),
            "vi_b": dict(vi_b, wl=None, fl=None, iv=None, spectrum=None, continuum=None),
            "sh_h1": sh_h1, "sh_h2": sh_h2,
            "fa_h1": fa_h1_result, "fa_h2": fa_h2_result,
            "hs": hs_result, "ra": ra_result,
            "elapsed_s": round(elapsed, 1),
        }
