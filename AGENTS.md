# AGENTS.md — CataLogA

Guidance for AI coding agents working in this repository. Assumes no prior
knowledge of the project.

## Project overview

CataLogA ("Catastrophe + Log + Agent") detects **redshift catastrophes** in
DESI spectroscopy — cases where the Redrock template-fitting pipeline assigns
a wrong redshift (sky-line mismatch, χ² local minimum, template mismatch).
Such failures bias BAO and large-scale-structure cosmology.

Core idea: DESI takes **repeat observations** of the same target. Both spectra
go through Redrock; if |z₁ − z₂| ≥ `DZ_THRESHOLD` (default 0.01), the target
is flagged as a suspected catastrophe and a chain of LLM agents
(**SH → FA → HS → RA**) audits it layer by layer.

The project is research code, ported largely from a sibling project
**FORMA** (`~/code/FORMA/`). Much of the numerical layer is a deliberate
verbatim port — see the porting rule below.

## Technology stack

- **Python 3.10+** (developed in a conda env named `cataloga`; the base env
  lacks `astropy`).
- Numerical: numpy, scipy, astropy (FITS I/O), PyWavelets (listed but CWT is
  actually pure numpy/scipy in `tools/features.py`), specutils, matplotlib.
- LLM: langchain-core, langchain-openai (`ChatOpenAI` against an
  OpenAI-compatible API — DeepSeek by default), langgraph, pydantic,
  tiktoken, python-dotenv.
- No `pyproject.toml` / `setup.py` — **not an installable package**. Both
  scripts do `sys.path.insert(0, <repo>/src)`; imports are
  `from cataloga.tools.lines import predict_lines` with `src/` on the path.
- No build step, no linter config, **no test suite** (see Testing).

## Setup and run commands

```bash
conda activate cataloga                     # or: conda run -n cataloga python <script>
pip install -r requirements.txt

cp .env_example .env                        # then edit: LLM_API_KEY is required

python scripts/preprocess.py                # scan DESI data → CSV + symlinks + targets.txt
python scripts/preprocess.py --force        # rescan even if CSV exists

python scripts/run_pipeline.py              # targets from .env TARGETID
python scripts/run_pipeline.py 39628250216924756   # CLI override: single ID
python scripts/run_pipeline.py --all               # CLI override: all targets
```

`TARGETID` (in `.env` or CLI) supports: a single ID, comma-separated IDs,
`all`, `tail-N` / `head-N` (of `targets.txt`, ordered by |Δz| desc), and
Python slice syntax `[10:]`, `[:30]`, `[8:10,17:50]`.

## Configuration

All runtime config comes from `.env` (loaded by both scripts via
`python-dotenv`) read in `src/cataloga/core/config.py` — a plain Python class
(no Pydantic despite the requirement listing). Groups of variables:

- LLM: `LLM_API_KEY` (required), `LLM_BASE_URL` (default
  `https://api.deepseek.com`), `LLM_MODEL` (default `deepseek-v4-pro`),
  `LLM_TEMPERATURE`, `LLM_MAX_TOKENS` (empty = DeepSeek auto 65536),
  `LLM_THINKING` (enabled/disabled; tool-calling mode always disables
  thinking), `LLM_STREAMING` (live ReAct output to terminal + `*_react.md`).
- CWT feature detection: `CWT_SNR_THRESH` (8.0), `CWT_MIN_RIDGE_LENGTH` (4),
  `CWT_N_SCALES` (24), `CWT_MIN_WIDTH` (1.0), `CWT_MAX_WIDTH` (80.0).
- Agent recursion limits: `MAX_TURNS_SH/FA/HS/RA` (500 each).
- Stage retry: `STAGE_RETRIES` (default 1), `STAGE_RETRY_DELAY` (30 s).
  Any failed LLM stage (SH/FA/HS/RA) is retried this many times; if all
  attempts fail the target fails — degraded stage results never flow
  downstream. An SH run that ends without a non-empty
  `sh_lines_{H1,H2}.csv` also counts as a stage failure.
- Paths: `DATA_ROOT` (`.data/test_catas`), `INTERMEDIATE_DIR`,
  `OUTPUT_DIR`, `DZ_THRESHOLD` (0.01). The checked-out `.env` points these
  at `.data/input` and `.data/output`. Both absolute and relative paths are
  accepted; relative paths are anchored at the repo root (not the CWD), so
  the scripts work from any directory.

**Hard-coded path**: `preprocess.py` searches FITS under
`{DATA_ROOT}/spectro/loa/tiles/cumulative/{TILEID}/{NIGHT}/`. This prefix is
not configurable via `.env`; change `scan_redrock_files()` if your data
layout differs.

## Repository layout

```
scripts/
├── preprocess.py          # scan DESI redrock FITS, find repeat-obs pairs, symlink inputs
├── run_pipeline.py        # entry point: resolve targets, run PipelineRunner per target
└── CataLogA/              # empty placeholder dir
src/cataloga/              # main package (PYTHONPATH: src/)
├── pipeline.py            # PipelineRunner: async orchestration of the full chain
├── core/
│   ├── config.py          # Config from env vars (plain class)
│   └── llm.py             # ChatOpenAI factory; patches payload so DeepSeek keeps max_tokens
├── tools/                 # numerical layer, NO LLM calls
│   ├── vi.py              # run_vi(): load spectrum → CWT → masked Chebyshev continuum
│   ├── vi_utils.py        # DESI FITS loading, arm-overlap cleaning, quality masking (from FORMA VI.py)
│   ├── spectrum.py        # load_coadd_spectrum / merged_spectrum / load_redrock_info
│   ├── features.py        # Ricker-wavelet CWT ridge detection (pure numpy/scipy)
│   ├── continuum.py       # iterative Chebyshev continuum fit with CWT-feature masking
│   ├── fitting.py         # fit_peak() (Gaussian+linear), fit_doublet()
│   ├── lines.py           # rest-frame line table from .knowledge/lines.md → predict_lines(z)
│   ├── detect.py          # [O II] 3727 unresolved-doublet slope-change detector
│   ├── evaluate.py        # pre-LLM numerical hypothesis scoring
│   ├── plotting.py        # cwt_features_*.png and fa_cleaned_*.png figures
│   └── inputs.py          # TargetInput dataclass; load_target()/list_targets() over INTERMEDIATE_DIR
├── agents/
│   ├── common/
│   │   ├── base_agent.py      # BaseAgent: skill loading, lazy LLM, retry, JSON-block parsing
│   │   └── continuation.py    # continue-on-truncation loop (finish_reason == "length")
│   └── multi_agents/
│       ├── sh.py              # SingleHypothesis agent (tools: fit_peak, fit_doublet, read_spectrum_region, ...)
│       ├── fa.py              # FeatureAuditor agent (audits each claimed line: KEEP/FLAG/REMOVE)
│       ├── hs.py              # HypothesisSynthesis agent (verdict: PREFER_H1/PREFER_H2/INDETERMINATE)
│       ├── ra.py              # ResultAuditor agent (independent catastrophe root-cause diagnosis)
│       └── _sh_prompt.py / _fa_prompt.py / _hs_prompt.py   # user-message builders
├── harness/tools.py       # LLM @tool functions (closure-bound to in-memory spectra);
│                          # build_tools() single-spectrum, build_dual_tools() dual-spectrum,
│                          # plus grep_kb() over data/kb/*.md
└── data/
    ├── skills/            # LLM system prompts: SH_skill.md, FA_skill.md, HS_synthesis_skill.md, RA_skill.md
    └── kb/                # knowledge base searched by grep_kb: classification, ionization, lines, composite_profile

.knowledge/lines.md        # rest-frame wavelength catalogue (Python tuples)
.data/test_catas/          # DESI loa test dataset (~7 GB, gitignored), coadd/redrock FITS pairs
.data/input/, .data/output/  # active intermediate + output dirs (per current .env)
.tmp/                      # legacy plotting scripts (reference only, not wired into the pipeline)
.repo_info/test_data/architecture.html  # Chinese overview of the test dataset
cross_hypothesis_comparison.md          # worked example write-up for TID 39628250216924756
```

Note: `src/cataloga/agents/` has no `__init__.py` files (namespace packages);
only `cataloga/` and `cataloga/core/` have them.

## Pipeline architecture

```
VI(coadd-A) ║ VI(coadd-B)        parallel: FITS load → mask → CWT features → continuum
      │
 SH-H1 ║ SH-H2                   each hypothesis verified on ITS OWN spectrum
      │
 FA-H1 ║ FA-H2                   parallel cross-audit: is each claimed feature real?
      │
 HS (dual-spectrum)              synthesis verdict over both FA catalogs
 RA (dual-spectrum)               independent catastrophe diagnosis
```

Orchestrated async in `src/cataloga/pipeline.py` (`PipelineRunner.run()`);
`asyncio.to_thread` for the numerical VI stage, `asyncio.gather` for the
parallel SH/FA LLM stages. Per-target outputs land in
`{OUTPUT_DIR}/{targetid}/`: `cwt_features_{A,B}.png`, `sh_lines_{H1,H2}.csv`,
`sh_{H1,H2}_react.md`, `fa_cleaned_{H1,H2}.png`, `fa_{H1,H2}_{react.md,verdict.json}`,
`hs_{react.md,verdict.json}`, `ra_{react.md,verdict.json}`.

Input convention (built by `preprocess.py`, consumed by `tools/inputs.py`):
`{INTERMEDIATE_DIR}/{targetid}/{coadd,redrock}-{A,B}.fits` as absolute
symlinks into `DATA_ROOT`, plus `{INTERMEDIATE_DIR}/targets.txt`.

## Code conventions

- Docstrings and code comments are in **English**; user-facing docs
  (README.md) are in Chinese. Match the file you edit.
- Module docstrings routinely note which FORMA file the code was ported from
  (e.g. "Ported from FORMA `harness/tools.py`"). Keep these attribution
  lines when editing.
- Agents subclass `BaseAgent`, set `_SKILL_DIR` (`src/cataloga/data/skills`)
  and `_skill_file`, and implement `build_user_message()`.
- LLM tools are built by closure over in-memory `(wl, fl, iv)` arrays
  (`harness/tools.py: build_tools` / `build_dual_tools`) — zero file I/O per
  tool call. Do not reintroduce per-call FITS loading.
- Config values are read once in `core/config.py` from env vars with
  defaults; thread them through `Config` rather than reading `os.environ`
  elsewhere (`preprocess.py`, which is standalone, is the exception).

### FORMA porting rule (important)

When porting a module/function from FORMA (`~/code/FORMA/`):

1. Copy the original FORMA file verbatim into the target path.
2. Fix imports/dependencies only (add new packages to `requirements.txt`).
3. Only then adapt interfaces to CataLogA conventions.
4. **Never re-derive the algorithm** unless there is a confirmed bug —
   hand-ported "equivalent" code has repeatedly introduced subtle numerical
   differences (L1 vs L2 normalization in CWT, median-filter vs Chebyshev
   ordering, missing NaN guards).

## Testing instructions

There is **no test suite, no CI, no lint configuration**. Verification is
empirical:

- Import smoke check: `conda run -n cataloga python -c "from cataloga.pipeline import PipelineRunner"`.
- The flagship validation case is TARGETID `39628250216924756`
  (QSO/Lya_failure, H1 z=0.2264 GALAXY vs H2 z=2.9522 QSO). A full pipeline
  run on it should return `PREFER_H2`; the expected analysis is documented in
  `cross_hypothesis_comparison.md`. Running it costs real LLM API calls.
- `python scripts/preprocess.py` is cheap and self-contained — use it to
  sanity-check data-path changes.

## Scientific caveats baked into the code

- **CWT is blind to broad QSO lines** (Lyα, C IV, C III] with FWHM ≈ 100 Å
  exceed the 1–80 px Ricker scales). Broad-line evidence comes from
  `fit_peak`; CWT is for narrow lines.
- **R/Z arm boundary 7520–7620 Å** is noisy (CCD stitching artifacts);
  features there are unreliable. B/R overlap 5760–5800 Å is benign.
- **INDETERMINATE is a valid HS verdict**, not a failure — HS must not be
  "fixed" to force a preference.
- Lyα asymmetry: single-Gaussian fits underpredict S/N; S/N ≥ 2 +
  Δχ²/n ≥ 1 → at least MARGINAL.

## Security considerations

- `.env` contains `LLM_API_KEY` — it is gitignored; never commit it or echo
  its contents. `.env_example` is the safe template.
- Pipeline outputs are written only under `OUTPUT_DIR`; inputs under
  `INTERMEDIATE_DIR` are absolute symlinks into `DATA_ROOT` — do not
  dereference-and-modify them; the original DESI FITS must stay read-only.
- Open large FITS files with `memmap=True` (~490 MB per redrock file).
- Pipeline runs make paid external LLM API calls; `TARGETID=all` can launch
  many. Confirm scope before batch runs.
- Git mutations (commit/push/reset) are not part of the normal workflow —
  ask before performing them.
