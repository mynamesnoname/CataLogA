#!/usr/bin/env python
"""Standalone plot script — delegates to ``cataloga.tools.plotting``.

Usage::

    python scripts/plot_results.py 39628250216924756
"""

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
except ImportError:
    pass

from cataloga.tools.inputs import load_target
from cataloga.tools.spectrum import load_coadd_spectrum, merged_spectrum
from cataloga.tools.features import find_features_cwt
from cataloga.tools.plotting import plot_cwt_overview, plot_hypothesis_lines
from cataloga.core.config import Config


def main():
    parser = argparse.ArgumentParser(description="Plot CataLogA results for one target")
    parser.add_argument("targetid", type=int)
    parser.add_argument("--input-dir", default=os.environ.get("INPUT_DIR", "input"))
    parser.add_argument("--output-dir", default=os.environ.get("OUTPUT_DIR", "output"))
    args = parser.parse_args()

    tid = args.targetid
    out = os.path.join(args.output_dir, str(tid))

    ti = load_target(args.input_dir, tid)
    sp = load_coadd_spectrum(ti.coadd_b, tid)
    wl, fl, _iv = merged_spectrum(sp)

    cfg = Config()
    peaks, troughs = find_features_cwt(
        wl, fl,
        snr_thresh=cfg.cwt_snr_thresh,
        min_ridge_length=cfg.cwt_min_ridge_length,
        n_scales=cfg.cwt_n_scales,
        min_scale=cfg.cwt_min_width,
        max_scale=cfg.cwt_max_width,
    )

    print(f"Target {tid}: {len(peaks)} peaks, {len(troughs)} troughs")
    plot_cwt_overview(wl, fl, peaks, troughs,
                      os.path.join(out, "cwt_features.png"))

    for label in ("H1", "H2"):
        plot_hypothesis_lines(wl, fl,
                              os.path.join(out, f"sh_lines_{label}.csv"),
                              os.path.join(out, f"fa_cleaned_{label}.png"),
                              label=label)


if __name__ == "__main__":
    main()
