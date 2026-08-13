"""LLM client factory.

Wraps ``langchain_openai.ChatOpenAI`` when available.

Key adaptation for DeepSeek: patches ``_get_request_payload`` to preserve
``max_tokens`` in the API request body.  langchain-openai >= 1.x
unconditionally renames ``max_tokens`` → ``max_completion_tokens`` (for
OpenAI API compat), but DeepSeek only recognises ``max_tokens`` and ignores
``max_completion_tokens``, silently falling back to its default (8192).
"""

import os


def _detect_vendor(base_url: str) -> str:
    url = base_url.lower()
    if "deepseek" in url:
        return "deepseek"
    if "openai" in url:
        return "openai"
    if "aliyuncs" in url or "dashscope" in url or "qwen" in url:
        return "qwen"
    if "anthropic" in url:
        return "anthropic"
    return "unknown"


def _is_anthropic_model(model: str) -> bool:
    return model.lower().startswith("claude")


def _build_thinking_extra_body(mode: str, vendor: str):
    """Build thinking-related extra_body for the model vendor."""
    if vendor == "deepseek":
        return {"thinking": {"type": mode}}
    if vendor == "qwen":
        return {"enable_thinking": mode == "enabled"}
    return None


def create_chat_anthropic(
    model: str,
    api_key: str,
    base_url: str,
    temperature: float = 0.1,
    max_tokens: int | None = None,
    thinking: str = "disabled",
):
    """Create a ChatAnthropic instance (native Anthropic API, not OpenAI-compatible)."""
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        raise ImportError(
            "langchain-anthropic not installed.  Install with:\n"
            "  pip install langchain-anthropic"
        )

    # Sampling params (temperature/top_p/top_k) are rejected on current-gen
    # Claude models (Opus 5, Sonnet 5, Opus 4.7+) — omit entirely rather than
    # pass the OpenAI-style default of 0.1.
    kwargs = dict(model=model, api_key=api_key)
    kwargs["max_tokens"] = max_tokens or 16000
    # Only pass base_url if it actually points at Anthropic's API (or a
    # compatible proxy) — the DeepSeek default in .env is not valid here.
    if base_url and "anthropic" in base_url.lower():
        kwargs["base_url"] = base_url
    # Claude Opus 5 thinks adaptively BY DEFAULT when `thinking` is omitted
    # (unlike Opus 4.8, where omission meant off) — so "disabled" must be
    # passed explicitly, or tool-calling agents that rely on plain-text
    # final answers can silently get back multi-block content instead.
    kwargs["thinking"] = {"type": "adaptive" if thinking == "enabled" else "disabled"}
    # Auto-cache the last cacheable block on every request (direct Anthropic
    # API only — not Bedrock/Vertex). In a growing multi-turn tool-calling
    # loop this caches the entire prefix (tools + skill system prompt + all
    # prior turns) each time, so every subsequent turn only pays full price
    # for what's new since the last call — the skill files here run
    # 6.5K-37K chars and get resent on every ReAct turn without this.
    kwargs["model_kwargs"] = {"cache_control": {"type": "ephemeral"}}

    return ChatAnthropic(**kwargs)


def create_chat_openai(
    model: str,
    api_key: str,
    base_url: str,
    temperature: float = 0.1,
    max_tokens: int | None = None,
    thinking: str = "disabled",
):
    """Create a chat model instance — ChatAnthropic for Claude models, else ChatOpenAI.

    For DeepSeek (via ChatOpenAI), patches ``_get_request_payload`` to keep
    ``max_tokens`` after langchain-openai renames it to ``max_completion_tokens``.
    """
    if _is_anthropic_model(model) or _detect_vendor(base_url) == "anthropic":
        return create_chat_anthropic(
            model=model, api_key=api_key, base_url=base_url,
            temperature=temperature, max_tokens=max_tokens, thinking=thinking,
        )

    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        raise ImportError(
            "langchain-openai not installed.  Install with:\n"
            "  pip install langchain-openai"
        )

    vendor = _detect_vendor(base_url)
    extra_body = _build_thinking_extra_body(thinking, vendor)

    kwargs = dict(model=model, api_key=api_key, base_url=base_url, temperature=temperature)
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if extra_body:
        kwargs["extra_body"] = extra_body

    llm = ChatOpenAI(**kwargs)

    # ── DeepSeek max_tokens monkey-patch ──
    # langchain-openai >= 1.x renames max_tokens → max_completion_tokens in
    # _get_request_payload.  DeepSeek ignores max_completion_tokens and
    # silently falls back to its default (8192).  We restore the original key.
    if vendor == "deepseek" and max_tokens is not None:
        _orig = llm._get_request_payload

        def _patched(self, input_, *, stop=None, **kw):
            payload = _orig(input_, stop=stop, **kw)
            if "max_completion_tokens" in payload:
                payload["max_tokens"] = payload.pop("max_completion_tokens")
            return payload

        llm._get_request_payload = _patched.__get__(llm, type(llm))

    return llm


def resolve_max_tokens(base_url: str = "") -> int | None:
    """Resolve max_tokens from env or provider defaults.

    When unset and using DeepSeek, defaults to 65536 to minimise truncation.
    """
    env_val = os.environ.get("LLM_MAX_TOKENS", "").strip()
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass
    base_url = (base_url or os.environ.get("LLM_BASE_URL", "")).lower()
    if "deepseek" in base_url:
        return 65536
    return None
