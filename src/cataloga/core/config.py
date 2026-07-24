"""Configuration — plain Python (no Pydantic dependency).

Populates from environment variables.
"""

import os

from cataloga.core.llm import resolve_max_tokens


class Config:
    """CataLogA runtime configuration."""

    def __init__(
        self,
        llm_api_key: str = "",
        llm_base_url: str = "",
        llm_model: str = "",
        llm_temperature: float | None = None,
        llm_max_tokens: int | None = None,
        llm_thinking: str = "",
        llm_streaming: bool = False,
        data_root: str = ".data/test_catas",
        intermediate_dir: str = "",
        output_dir: str = "",
        targetid: str = "",
    ):
        self.llm_api_key = llm_api_key or os.environ.get("LLM_API_KEY", "")
        self.llm_base_url = llm_base_url or os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
        self.llm_model = llm_model or os.environ.get("LLM_MODEL", "deepseek-v4-pro")
        self.llm_temperature = (
            llm_temperature if llm_temperature is not None
            else float(os.environ.get("LLM_TEMPERATURE", "0.1")))
        self.llm_max_tokens = llm_max_tokens or resolve_max_tokens(self.llm_base_url)
        self.llm_thinking = llm_thinking or os.environ.get("LLM_THINKING", "disabled")
        self.llm_streaming = llm_streaming or os.environ.get("LLM_STREAMING", "").lower() in ("1", "true", "yes")
        self.data_root = data_root or os.environ.get("DATA_ROOT", ".data/test_catas")
        self.intermediate_dir = intermediate_dir or os.environ.get("INTERMEDIATE_DIR", "input")
        self.output_dir = output_dir or os.environ.get("OUTPUT_DIR", "output")
        self.targetid = targetid or os.environ.get("TARGETID", "")
        self.dz_threshold = float(os.environ.get("DZ_THRESHOLD", "0.01"))

        # ── CWT feature detection ────────────────────────────
        self.cwt_snr_thresh = float(
            os.environ.get("CWT_SNR_THRESH", "8.0"))
        self.cwt_min_ridge_length = int(
            os.environ.get("CWT_MIN_RIDGE_LENGTH", "4"))
        self.cwt_n_scales = int(
            os.environ.get("CWT_N_SCALES", "24"))
        self.cwt_min_width = float(
            os.environ.get("CWT_MIN_WIDTH", "1.0"))
        self.cwt_max_width = float(
            os.environ.get("CWT_MAX_WIDTH", "80.0"))

        # ── LangChain agent recursion limits (FORMA defaults) ─
        self.max_turns_sh = int(os.environ.get("MAX_TURNS_SH", "500"))
        self.max_turns_fa = int(os.environ.get("MAX_TURNS_FA", "500"))
        self.max_turns_hs = int(os.environ.get("MAX_TURNS_HS", "500"))
        self.max_turns_ra = int(os.environ.get("MAX_TURNS_RA", "500"))

        # ── Stage-level retry for LLM stages (SH/FA/HS/RA) ─────
        # A failed stage is retried up to this many times; if all attempts
        # fail, the target fails — degraded results never flow downstream.
        self.stage_retries = int(os.environ.get("STAGE_RETRIES", "1"))
        self.stage_retry_delay = float(os.environ.get("STAGE_RETRY_DELAY", "30"))

        # Spectrum preprocessing — DESI defaults
        self.arm_names = ["B", "R", "Z"]
        self.arm_wavelength_ranges = [(3600, 5800), (5760, 7620), (7520, 9824)]
