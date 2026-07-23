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
    return "unknown"


def _build_thinking_extra_body(mode: str, vendor: str):
    """Build thinking-related extra_body for the model vendor."""
    if vendor == "deepseek":
        return {"thinking": {"type": mode}}
    if vendor == "qwen":
        return {"enable_thinking": mode == "enabled"}
    return None


def create_chat_openai(
    model: str,
    api_key: str,
    base_url: str,
    temperature: float = 0.1,
    max_tokens: int | None = None,
    thinking: str = "disabled",
):
    """Create a ChatOpenAI instance.

    For DeepSeek, patches ``_get_request_payload`` to keep ``max_tokens``
    after langchain-openai renames it to ``max_completion_tokens``.
    """
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
