# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

CataLogA ("Catastrophe + Log + Agent") is an early-stage project to build an agent that detects redshift catastrophes in DESI spectroscopy — cases where the Redrock template-fitting pipeline assigns a wrong redshift (e.g. sky/airglow lines mismatched as astrophysical features, or a wrong χ² local minimum winning the fit). Such failures bias BAO and large-scale-structure cosmology. The core validation idea: compare redshifts from repeat observations of the same source; a large |Z₁ − Z₂| flags a suspected catastrophe.

No application code exists yet — the tracked repo is only a stub README, MIT license, and .gitignore. There is no build, lint, or test infrastructure. The working material lives in untracked directories described below.

## Environment

Use the dedicated conda env — the base env lacks astropy:

```bash
conda activate cataloga        # Python 3.10: astropy 6.1.3, numpy 2.2, scipy, matplotlib
# or one-off:
conda run -n cataloga python <script.py>
```

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
- `.data/test_catas/README.md` was written for the standalone dataset repo and is partly aspirational: `scripts/create_manifest.py` and `requirements.txt` do not exist, and `inspect_spectrum.py` has no CLI despite the documented `--target-index`/`--show` flags.
- `test_catas.zip` at the repo root is the source archive for `.data/test_catas/`.

## Reference material

- `.knowledge/lines.md` — rest-frame wavelengths (Å) of the standard optical emission/absorption lines (Lyα, C IV, [O II], Balmer series, Ca H&K, [O III], [N II], [S II], Ca triplet, …) as Python tuples, for spectral-line overlays and identification.
- `.repo_info/test_data/architecture.html` — Chinese-language overview of the test dataset (stats, taxonomy tables, FITS field notes, science background). Generated 2026-07-17; some details lag the current `inspect_spectrum.py` (it still lists an `Ha_artifact` subclass whose tiles 1270/10380 are not in the dataset, and an outdated `redux_root`).
