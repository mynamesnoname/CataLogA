#!/usr/bin/env python
"""Plot redshift-catastrophe spectra from the curated test_catas taxonomy.

Reuses the BGS/LRG/ELG/QSO taxonomy and get_coadd_redrock_files() from
.data/test_catas/examples/inspect_spectrum.py. For each catastrophe subclass
the target is located automatically:

- "pair" subclasses exploit that the two (tile, night, petal) entries are
  repeat observations of overlapping sky: the same TARGETID appears in both,
  and the catastrophe is the pair whose two redshifts disagree.
- "perfile" subclasses select one target per file from the redrock table
  (e.g. QSO targets classified as non-QSO for wrong_type).

Output: PNG figures under output/catastrophe_spectra/.
"""

import ast
import os

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from astropy.convolution import Gaussian1DKernel, convolve
from astropy.io import fits

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, ".data", "test_catas")
REDUX = os.path.join(DATA, "spectro")
OUTDIR = os.path.join(REPO, "output", "catastrophe_spectra")

C_KMS = 299792.458
LRG_BIT, ELG_BIT, QSO_BIT, BGS_BIT = 2**0, 2**1, 2**2, 2**60
OII_REST, LYA_REST = 3727.0, 1216.0


def load_taxonomy():
    """Exec the collaborator's inspect_spectrum.py and return its namespace.

    The module ends with a demo call that resolves files relative to the
    dataset root, so temporarily chdir there.
    """
    src = os.path.join(DATA, "examples", "inspect_spectrum.py")
    ns = {}
    cwd = os.getcwd()
    try:
        os.chdir(DATA)
        with open(src) as fh:
            exec(compile(fh.read(), src, "exec"), ns)
    finally:
        os.chdir(cwd)
    return ns


def load_lines():
    with open(os.path.join(REPO, ".knowledge", "lines.md")) as fh:
        return ast.literal_eval("[" + fh.read() + "]")


def load_redrock(rrfile):
    with fits.open(rrfile, memmap=True) as h:
        zs = h["REDSHIFTS"].data
        fm = h["FIBERMAP"].data
        return {
            "tid": zs["TARGETID"].copy(),
            "z": zs["Z"].copy(),
            "zwarn": zs["ZWARN"].copy(),
            "spectype": np.char.strip(zs["SPECTYPE"]),
            "dchi2": zs["DELTACHI2"].copy(),
            "desi": fm["DESI_TARGET"].copy(),
            "objtype": np.char.strip(fm["OBJTYPE"]),
        }


def load_spectrum(coaddfile, targetid):
    cams = {}
    with fits.open(coaddfile, memmap=True) as h:
        row = int(np.where(h["FIBERMAP"].data["TARGETID"] == targetid)[0][0])
        for cam in "BRZ":
            wave = h[f"{cam}_WAVELENGTH"].data.astype(float)
            flux = h[f"{cam}_FLUX"].data[row].astype(float)
            ivar = h[f"{cam}_IVAR"].data[row].astype(float)
            mask = h[f"{cam}_MASK"].data[row]
            flux[(ivar <= 0) | (mask != 0)] = np.nan
            ivar[(ivar <= 0) | (mask != 0)] = np.nan
            cams[cam] = (wave, flux, ivar)
    return cams


def join_pair(a, b):
    common, ia, ib = np.intersect1d(a["tid"], b["tid"], return_indices=True)
    keep = (a["objtype"][ia] == "TGT") & (b["objtype"][ib] == "TGT") & (common > 0)
    ia, ib = ia[keep], ib[keep]
    za, zb = a["z"][ia], b["z"][ib]
    dv = np.abs(za - zb) / (1 + np.minimum(za, zb)) * C_KMS
    return {
        "tid": common[keep], "dv": dv,
        "za": za, "zb": zb,
        "wa": a["zwarn"][ia], "wb": b["zwarn"][ib],
        "sa": a["spectype"][ia], "sb": b["spectype"][ib],
        "da": a["dchi2"][ia], "db": b["dchi2"][ib],
        "bits": a["desi"][ia],
    }


def pick_sky(j, zsky, tol, bit):
    """Discrepant repeat pair where one confident (ZWARN=0) z sits on zsky."""
    on_sky = ((np.abs(j["za"] - zsky) < tol) & (j["wa"] == 0)) | (
        (np.abs(j["zb"] - zsky) < tol) & (j["wb"] == 0)
    )
    cand = on_sky & (j["dv"] > 1000) & ((j["bits"] & bit) != 0)
    return None if not cand.any() else np.where(cand)[0][np.argmax(j["dv"][cand])]


def pick_confident_disagreement(j, bit, min_dchi2):
    """Both fits ZWARN=0 and confident, yet redshifts disagree wildly."""
    cand = (
        (j["wa"] == 0) & (j["wb"] == 0)
        & (np.minimum(j["da"], j["db"]) > min_dchi2)
        & (j["dv"] > 3000) & ((j["bits"] & bit) != 0)
    )
    return None if not cand.any() else np.where(cand)[0][np.argmax(j["dv"][cand])]


def pick_bad_pair(j, bit):
    """Both fits flagged (ZWARN!=0) and mutually inconsistent.

    DARK tiles mix LRG/ELG/QSO fibers, so if no pair carries the requested
    target bit, fall back to any real target.
    """
    base = (j["wa"] != 0) & (j["wb"] != 0) & (j["dv"] > 3000)
    cand = base & ((j["bits"] & bit) != 0)
    if not cand.any():
        cand = base
    return None if not cand.any() else np.where(cand)[0][np.argmax(j["dv"][cand])]


def pick_wrong_type(d):
    """QSO target confidently classified as something other than QSO."""
    cand = ((d["desi"] & QSO_BIT) != 0) & (d["objtype"] == "TGT") & (d["zwarn"] == 0) \
        & (d["spectype"] != "QSO")
    idx = np.where(cand)[0]
    return None if idx.size == 0 else idx[np.argmax(d["dchi2"][idx])]


def pick_bad_spec(d, bit):
    """Flagged target with the most ambiguous fit (lowest DELTACHI2)."""
    cand = ((d["desi"] & bit) != 0) & (d["objtype"] == "TGT") & (d["zwarn"] != 0)
    idx = np.where(cand)[0]
    return None if idx.size == 0 else idx[np.argmin(d["dchi2"][idx])]


def smooth(flux, stddev=2.0):
    return convolve(flux, Gaussian1DKernel(stddev), boundary="extend")


CAM_COLORS = {"B": "#3b7dd8", "R": "#2ca02c", "Z": "#d62728"}


def plot_panel(ax, cams, z, lines, label, zoom_center=None, zoom_width=150.0):
    smoothed_all = []
    for cam in "BRZ":
        wave, flux, ivar = cams[cam]
        ax.plot(wave, flux, color="0.75", lw=0.4, zorder=1)
        sm = smooth(flux)
        smoothed_all.append(sm)
        ax.plot(wave, sm, color=CAM_COLORS[cam], lw=0.9, zorder=3)
        with np.errstate(invalid="ignore"):
            sigma = 1.0 / np.sqrt(ivar)
        ax.fill_between(wave, 0, sigma, color="0.55", alpha=0.18, lw=0, zorder=0)

    allsm = np.concatenate(smoothed_all)
    finite = allsm[np.isfinite(allsm)]
    lo, hi = np.nanpercentile(finite, [0.5, 99.5])
    pad = 0.15 * (hi - lo)
    ax.set_ylim(min(lo - pad, -0.5), hi + 3.5 * pad)
    ax.set_xlim(3600, 9824)

    ymax = ax.get_ylim()[1]
    for rest, name in lines:
        obs = rest * (1 + z)
        if 3600 < obs < 9824:
            ax.axvline(obs, color="0.35", lw=0.5, ls="--", alpha=0.6, zorder=2)
            ax.text(obs, ymax * 0.97, name, rotation=90, fontsize=6,
                    ha="right", va="top", color="0.25")

    ax.text(0.008, 0.95, label, transform=ax.transAxes, fontsize=8.5,
            va="top", ha="left",
            bbox=dict(facecolor="white", alpha=0.85, edgecolor="0.6", pad=3))
    ax.set_ylabel("Flux [$10^{-17}$ erg s$^{-1}$ cm$^{-2}$ $\\AA^{-1}$]", fontsize=8)

    if zoom_center is not None and 3600 < zoom_center < 9824:
        axins = ax.inset_axes([0.68, 0.52, 0.30, 0.44])
        for cam in "BRZ":
            wave, flux, ivar = cams[cam]
            sel = np.abs(wave - zoom_center) < zoom_width
            if sel.any():
                axins.plot(wave[sel], flux[sel], color=CAM_COLORS[cam], lw=0.7)
                with np.errstate(invalid="ignore"):
                    axins.fill_between(wave[sel], 0,
                                       1.0 / np.sqrt(ivar[sel]),
                                       color="0.55", alpha=0.25, lw=0)
        axins.axvline(zoom_center, color="k", lw=0.6, ls=":")
        axins.tick_params(labelsize=6)
        axins.set_title("zoom @ fitted line vs noise ($1/\\sqrt{ivar}$)", fontsize=6.5)


def describe(tag, z, spectype, zwarn, dchi2):
    return (f"{tag}   z={z:.4f}   SPECTYPE={spectype}   "
            f"ZWARN={int(zwarn)}   DELTACHI2={dchi2:.0f}")


def main():
    ns = load_taxonomy()
    get_files = ns["get_coadd_redrock_files"]
    lines = load_lines()
    os.makedirs(OUTDIR, exist_ok=True)

    def files(entry):
        t, n, p = entry
        return get_files(t, n, p, release="loa", redux_root=REDUX)

    pair_cases = [
        ("ELG", "sky_1p50", ns["ELG"]["sky_1p50"],
         lambda j: pick_sky(j, 1.50, 0.03, ELG_BIT), OII_REST,
         "sky-line catastrophe: fitted [OII] lands on the OH forest near 9350 A"),
        ("ELG", "sky_1p315", ns["ELG"]["sky_1p315"],
         lambda j: pick_sky(j, 1.315, 0.01, ELG_BIT), OII_REST,
         "sky-line catastrophe: z=1.315 puts [OII] on the 8630 A OH complex"),
        ("QSO", "Lya_failure", ns["QSO"]["Lya_failure"],
         lambda j: pick_confident_disagreement(j, QSO_BIT, 50), LYA_REST,
         "Lya misidentification: low-z GALAXY fit vs high-z QSO fit"),
        ("LRG", "absorp_artifact", ns["LRG"]["absorp_artifact"],
         lambda j: pick_confident_disagreement(j, LRG_BIT, 50), None,
         "artifact absorption feature drives two confident but incompatible fits"),
        ("LRG", "bad_spec", ns["LRG"]["bad_spec"],
         lambda j: pick_bad_pair(j, LRG_BIT), None,
         "low-quality spectrum: both repeat fits flagged and inconsistent"),
    ]

    for cls, sub, entries, selector, zoom_rest, note in pair_cases:
        fa, fb = files(entries[0]), files(entries[1])
        j = join_pair(load_redrock(fa["redrock"]), load_redrock(fb["redrock"]))
        k = selector(j)
        if k is None:
            print(f"[skip] {cls}/{sub}: no candidate found")
            continue
        tid = int(j["tid"][k])
        fig, axes = plt.subplots(2, 1, figsize=(13, 7.5), sharex=True)
        for ax, f, entry, z, w, s, d in [
            (axes[0], fa, entries[0], j["za"][k], j["wa"][k], j["sa"][k], j["da"][k]),
            (axes[1], fb, entries[1], j["zb"][k], j["wb"][k], j["sb"][k], j["db"][k]),
        ]:
            cams = load_spectrum(f["coadd"], tid)
            t, n, p = entry
            zoom = zoom_rest * (1 + z) if zoom_rest else None
            plot_panel(ax, cams, z, lines,
                       describe(f"tile {t} / night {n} / petal {p}", z, s, w, d),
                       zoom_center=zoom)
        axes[1].set_xlabel("Observed wavelength [$\\AA$]", fontsize=9)
        dv = j["dv"][k]
        fig.suptitle(f"{cls} {sub} - TARGETID {tid} - repeat observations disagree by "
                     f"{dv:,.0f} km/s\n{note}", fontsize=11)
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        out = os.path.join(OUTDIR, f"{cls}-{sub}-{tid}.png")
        fig.savefig(out, dpi=140)
        plt.close(fig)
        print(f"[ok] {cls}/{sub}: TARGETID {tid} dv={dv:,.0f} km/s -> {out}")

    perfile_cases = [
        ("QSO", "wrong_type", ns["QSO"]["wrong_type"], pick_wrong_type,
         "QSO target confidently classified as a different SPECTYPE"),
        ("BGS", "bad_spec", ns["BGS"]["bad_spec"],
         lambda d: pick_bad_spec(d, BGS_BIT),
         "flagged fits (ZWARN!=0) with near-degenerate chi2 minima"),
    ]

    for cls, sub, entries, selector, note in perfile_cases:
        fig, axes = plt.subplots(2, 1, figsize=(13, 7.5), sharex=True)
        picked = []
        for ax, entry in zip(axes, entries):
            f = files(entry)
            d = load_redrock(f["redrock"])
            i = selector(d)
            if i is None:
                print(f"[skip] {cls}/{sub} {entry}: no candidate")
                continue
            tid = int(d["tid"][i])
            picked.append(tid)
            cams = load_spectrum(f["coadd"], tid)
            t, n, p = entry
            plot_panel(ax, cams, d["z"][i], lines,
                       describe(f"tile {t} / night {n} / petal {p} - TARGETID {tid}",
                                d["z"][i], d["spectype"][i], d["zwarn"][i],
                                d["dchi2"][i]))
        axes[1].set_xlabel("Observed wavelength [$\\AA$]", fontsize=9)
        fig.suptitle(f"{cls} {sub} - one example per observation\n{note}", fontsize=11)
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        out = os.path.join(OUTDIR, f"{cls}-{sub}.png")
        fig.savefig(out, dpi=140)
        plt.close(fig)
        print(f"[ok] {cls}/{sub}: TARGETIDs {picked} -> {out}")


if __name__ == "__main__":
    main()
