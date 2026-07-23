# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

CataLogA ("Catastrophe + Log + Agent") is an early-stage project to build an agent that detects redshift catastrophes in DESI spectroscopy — cases where the Redrock template-fitting pipeline assigns a wrong redshift (e.g. sky/airglow lines mismatched as astrophysical features, or a wrong χ² local minimum winning the fit). Such failures bias BAO and large-scale-structure cosmology. The core validation idea: compare redshifts from repeat observations of the same source; a large |Z₁ − Z₂| flags a suspected catastrophe.

The tracked repo is a stub README + MIT license + .gitignore. Application code and working material live in untracked paths described below. No build, lint, or test infrastructure yet.

## Environment

Use the dedicated conda env — the base env lacks astropy:

```bash
conda activate cataloga        # Python 3.10: astropy 6.1.3, numpy 2.2, scipy, matplotlib
# or one-off:
conda run -n cataloga python <script.py>
```

## FORMA porting rule

When porting a module / function from FORMA (``~/code/FORMA/``):

1. **Copy-paste the original FORMA file** — drop it into the target CataLogA path verbatim.
2. **Fix imports and dependencies** — install missing packages, resolve import paths.
3. **Only then adapt the interface** — change function signatures, wiring, and state keys to match CataLogA conventions.
4. **Keep the algorithm untouched** unless there is a confirmed bug or a hard incompatibility that cannot be resolved at the import / interface layer.

This rule exists because hand-ported "equivalent" code has repeatedly introduced subtle numerical differences (L1 vs L2 normalisation in CWT, median-filter vs Chebyshev ordering, missing NaN guards). Copy-paste first, adapt second.

If the copied code requires packages not in ``requirements.txt``, install them in the ``cataloga`` conda env and add them to ``requirements.txt``.  Do not rewrite a dependency's work just to avoid a new package — that path already led to bugs.

## Pipeline Architecture (5-step, 3-module)

Validation workflow for redshift-catastrophe detection, designed 2026-07-19:

```
Module 1 (VI): load FITS → mask bad pixels → CWT feature detection → emit feature catalog
              + read redrock redshifts as input hypotheses (pre-computed by Python)

Module 2 (HA): SH×2 (parallel) — each hypothesis gets predict_lines(z) → cross-match
              with CWT features + pre-computed fit_peak → line catalog (LIKELY/MARGINAL/NOT_FOUND)
              FA×1 — cross-hypothesis feature audit: verify each claimed feature is physically
              real in the spectrum; output cleaned catalog (KEEP/FLAG/REMOVE)

Module 3 (HS+RA): Hypothesis Synthesis compares cleaned catalogs, produces verdict +
              catastrophe attribution. Result Auditor does independent review.
              (HS implemented 2026-07-19; RA not yet implemented.)

Module X:      SelfEvolve — when ground truth available, blind review of discrepancies.
              (Not yet implemented.)
```

Key methodological findings:
- **Broad QSO lines (Lyα, C IV, C III]) are invisible to CWT** — Ricker wavelet at 1–80 px scales misses features with FWHM ≈ 100 Å. For broad lines, use fit_peak (Gaussian+linear) as primary evidence; the Three-Question Test (peak clarity/neighborhood comparison) is for narrow lines only.
- **R/Z arm boundary (7520–7620 Å)** is noisy and prone to artifacts — flag or mask features here.
- **Lyα asymmetry**: single Gaussian underpredicts S/N. S/N ≥ 2 + Δχ²/n ≥ 1 → at least MARGINAL.
- **HS does NOT score or rank hypotheses** — LLM forms a qualitative impression by examining specific features, FA verdicts, and raw spectrum. INDETERMINATE is a valid scientific output (not a failure). Verdict: PREFER_H1 / PREFER_H2 / INDETERMINATE.
- **Full SH→FA→HS pipeline validated** on flagship case TID 39628250216924756 (QSO/Lya_failure): H1 (z=0.226) all 5 features FA-REMOVED as noise forests; H2 (z=2.952) Lyα FA-KEEP (S/N=3.8). HS correctly returned PREFER_H2.

## Project structure

```
src/cataloga/              ← main package (PYTHONPATH: src/)
├── tools/                 ← numerical layer (no LLM)
│   ├── vi_utils.py        ← FORMA VI.py: FITS loading + arm overlap cleaning
│   ├── spectrum.py         ← per-TARGETID FITS I/O (wraps vi_utils)
│   ├── lines.py            ← .knowledge/lines.md → predict_lines()
│   ├── fitting.py          ← fit_peak(), fit_doublet() (Gaussian + linear)
│   ├── features.py         ← Ricker CWT ridge detection (pure numpy/scipy)
│   ├── detect.py           ← [O II] slope-change detector
│   └── evaluate.py         ← pre-LLM numerical hypothesis scoring
├── core/                   ← infrastructure
│   ├── config.py           ← Pydantic Config (LLM + data paths + arm params)
│   ├── llm.py              ← ChatOpenAI factory (from FORMA)
│   ├── state.py            ← CatalogaState (TypedDict, 20 fields)
│   └── workflow.py         ← LangGraph StateGraph definition
├── agents/                 ← Phase 2: BaseAgent + ResultWriter + SH/FA/HS wrappers
│   ├── common/base_agent.py     ← skill loading, lazy LLM, retry, JSON parsing
│   ├── common/result_writer.py  ← standardized CSV/JSON/MD output writer
│   └── multi_agents/{sh,fa,hs}.py  ← agent wrappers (delegate to .test_src/ build logic)
├── harness/                ← @tool functions for LLM agents (Phase 3+)
└── data/                   ← skills + kb (Phase 2)

.test_src/                  ← dev sandbox; re-exports from cataloga.tools for backward compat
```

Import style: `from cataloga.tools.lines import predict_lines` (with `src/` on PYTHONPATH).
Old `sys.path.insert(0, ".test_src"); import lines` still works via `.test_src/__init__.py` shim.

## `.test_src/` — Agent tool modules (gitignored)

Port of FORMA's multi-agent spectroscopy tools, adapted for DESI coadd FITS:

| Module | Purpose | Key functions |
|---|---|---|
| `lines.py` | Rest-frame line table from `.knowledge/lines.md` | `predict_lines(z)` — observed λ for all lines at given z |
| `spectrum.py` | DESI coadd FITS I/O | `load_coadd_spectrum(path, targetid)` → B/R/Z dict; `read_spectrum_region()`; `merged_spectrum()` |
| `fitting.py` | Gaussian line fitting | `fit_peak(wl, fl, center_guess)` → center, S/N, FWHM, Δχ²/n; `fit_doublet()` |
| `features.py` | Ricker CWT feature detection | `find_features_cwt(wl, fl)` → emission/absorption catalogs (pure numpy/scipy, no pywt needed) |
| `detect.py` | [O II] unresolved-doublet signature | `detect_oii_slope_change(wl, fl, target_wl)` → valley or slope-change detection |
| `evaluate.py` | Rapid numerical hypothesis scoring | `evaluate_hypothesis()` + `compare_hypotheses()` — pre-LLM fast check |
| `sh.py` | SH agent prompt builder | `build_user_message()` — CWT table + predicted lines + pre-computed fit_peak results |
| `fa.py` | FA agent prompt builder | `build_user_message()` — contradiction matrix + doublet/O II/Lyα check sections |
| `hs.py` | HS agent prompt builder | `build_user_message()` — side-by-side FA catalogs + redrock conflict summary |
| `hs_utils.py` | HS helpers | `load_fa_catalog()` — parse FA CSV into catalog dict; `build_redrock_dict()` |

**Skills** (LLM system prompts, adapted from FORMA): `skills/SH_skill.md` (19K), `skills/FA_skill.md` (37K), `skills/HS_synthesis_skill.md` (8K).
**Knowledge base**: `kb/classification.md`, `kb/ionization.md`, `kb/lines.md`, `kb/composite_profile.md`.

All modules support both `from .test_src.xxx import ...` and `sys.path.insert(0, ".test_src"); import xxx`.

## Known Issues & Planned Improvements

### VI: arm boundary masking (not yet implemented)

DESI coadd spectra span three cameras with overlap zones:

| Boundary | Range | Issue |
|---|---|---|
| B/R overlap | 5760–5800 | Minor — two cameras agree, take median or B |
| R/Z gap | 7520–7620 | **Major** — CCD stitching artifacts, flux extremes, features here are unreliable |

Currently `spectrum.py` masks bad pixels (ivar≤0, MASK≠0) but does NOT mask arm boundaries. The R/Z gap caused C III] false positives in FA (±359Å uncertainty at ~7545Å). FORMA handles this in VI by reading arm ranges and masking boundary zones before downstream agents see the spectrum.

**Planned fix**: VI should output two spectrum versions:
1. **Raw** — arm boundaries marked but not removed (for FA/HS to inspect)
2. **Cleaned** — arm boundaries masked out (for CWT and SH — prevents false detection)

This lets FA/HS explicitly note "this feature falls in a masked boundary zone" rather than relying on verbal warnings.

## Test dataset (`.data/test_catas/`, gitignored, ~7 GB)

DESI `loa` production spectroscopy for 34 tile/night/petal combinations (observed 2021–2024): 68 FITS files as coadd/redrock pairs, following the DESI directory convention:

```
.data/test_catas/spectro/loa/tiles/cumulative/<TILEID>/<NIGHT>/
├── coadd-<PETAL>-<TILEID>-thru<NIGHT>.fits    # coadded spectra + fiber metadata (~52 MB)
└── redrock-<PETAL>-<TILEID>-thru<NIGHT>.fits  # Redrock v0.20.2 redshifts + fit details (~490 MB)
```

- Coadd HDUs: `FIBERMAP` (target table), `B_WAVELENGTH`/`B_FLUX` plus the R- and Z-channel equivalents, and inverse-variance arrays. Open with `astropy.io.fits` and `memmap=True` — the files are large.
- Redrock HDUs: `REDSHIFTS` (Z, ZERR, ZWARN, spectral type, χ²), `FIBERMAP`.
- `.data/test_catas/examples/inspect_spectrum.py` holds the curated target taxonomy: `BGS`/`LRG`/`ELG`/`QSO` dicts mapping science subclasses (`Ha_conf`, `absorp_Ha`, `OII_conf`, `sky_1p50`, `Lya_CIV`, `Lya_failure`, `wrong_type`, `bad_spec`, …) to `(tileid, night, petal)` tuples, plus `get_coadd_redrock_files()` — from the repo root call it with `redux_root='.data/test_catas/spectro'`, `release='loa'`.

Dataset caveats:

- Six tiles exist on disk but are absent from the taxonomy: 1705, 1828, 7965, 8083, 8678, 9159.
- `.data/test_catas/README.md` refers to nonexistent `scripts/create_manifest.py` and `requirements.txt`; `inspect_spectrum.py` has no CLI despite documented `--target-index`/`--show`.
- `test_catas.zip` at the repo root is the source archive for `.data/test_catas/`.

**Repeat-pair structure** (critical for catastrophe detection):
Each subclass has two (tile, night, petal) entries that are overlapping-sky repeat observations. Their redrock files share common TARGETIDs (5–42 per pair). To locate catastrophe candidates, intersect the two files on TARGETID (exclude sky fibers: TID>0, OBJTYPE='TGT') and rank by velocity difference Δv = c·|z_A−z_B|/(1+z_min). See `scripts/plot_catastrophes.py` for implementation.

**Discrepant pairs CSV**: `output/catastrophe_spectra/discrepant_pairs_abs_dz_ge_0.01.csv` — 41 pairs with |Δz| ≥ 0.01 across all 14 subclasses (266 common targets total). Columns: index, FromWhichType, FromWhichCatastrophe, targetid, spec1fits, z1, RedrockType1, zwarn1, dchi2_1, spec2fits, z2, RedrockType2, zwarn2, dchi2_2, abs_dz. Among them, 19 pairs have both ZWARN=0 (pipeline confident but wrong — strict catastrophes).

**Plotting**: `scripts/plot_catastrophes.py` — generates diagnostic spectrum figures (B/R/Z channels + line IDs + redshift annotations) for catastrophe subclasses. Outputs to `output/catastrophe_spectra/`.

## Reference material

- `.knowledge/lines.md` — rest-frame wavelengths (Å) of the standard optical emission/absorption lines (Lyα, C IV, [O II], Balmer series, Ca H&K, [O III], [N II], [S II], Ca triplet, …) as Python tuples, for spectral-line overlays and identification.
- `.repo_info/test_data/architecture.html` — Chinese-language overview of the test dataset (stats, taxonomy tables, FITS field notes, science background). Generated 2026-07-17; some details lag the current `inspect_spectrum.py` (it still lists an `Ha_artifact` subclass whose tiles 1270/10380 are not in the dataset, and an outdated `redux_root`).
