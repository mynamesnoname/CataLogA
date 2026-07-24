"""BaseAgent — adapted from FORMA ``agents/common/base_agent.py``.

Provides skill loading, LLM invocation with retry, JSON parsing, and
LangChain agent creation with tool-calling + continuation support.

Two run modes:
- ``call_llm()`` — simple system/user prompt → single LLM response (no tools)
- ``run_with_tools()`` — LangChain agent with tool-calling loop + continuation

Subclasses set ``agent_name`` and ``_SKILL_DIR``, and implement
``build_user_message()``.
"""

import re
import json
import asyncio
import logging
from pathlib import Path

from cataloga.core.config import Config
from cataloga.core.llm import create_chat_openai, _detect_vendor

# ── Retryable error keywords (aligned with FORMA) ──
_CONNECTION_KEYWORDS = (
    "connection reset", "connection refused", "remotedisconnected",
    "clientconnectorerror", "apiconnectionerror",
    "connect error", "network", "broken pipe", "eof occurred", "ssl",
)
_TIMEOUT_KEYWORDS = (
    "connectionerror", "connecttimeout",
    "timed out", "timeout", "readtimeout", "read timeout",
)
_RATE_LIMIT_KEYWORDS = (
    "rate limit", "insufficient_quota",
    "invalid_parameter_error", "function.arguments",
)


def _is_retryable(error_msg: str) -> bool:
    msg = error_msg.lower()
    return any(kw in msg for kw in _CONNECTION_KEYWORDS + _TIMEOUT_KEYWORDS + _RATE_LIMIT_KEYWORDS)


def _extract_json_block(raw: str):
    """Try to extract a JSON block from markdown text.

    Returns the parsed dict, or None if no JSON block found.
    """
    if not isinstance(raw, str):
        return raw
    # 1) ```json ... ``` with closing fence
    m = re.search(r'```json\s*(.*?)\s*```', raw, re.DOTALL)
    # 2) ```json ... (no closing fence, LLM sometimes forgets it)
    if not m:
        m = re.search(r'```json\s*(.+)$', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # 3) Bare JSON object containing common FA/HS/RA keys
    for key_pat in ['feature_verdicts|spectrum_quality|verdict',
                    '"verdict"',
                    '"recommendation"']:
        m = re.search(r'\{.*' + key_pat + r'.*\}', raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return None


def _parse_json(raw: str):
    """Try to parse raw LLM output as JSON.  Falls back to raw string."""
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$", "", raw.strip(),
        flags=re.IGNORECASE,
    ).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    try:
        import ast
        parsed = ast.literal_eval(cleaned)
        if isinstance(parsed, (dict, list)):
            return parsed
    except Exception:
        pass
    return cleaned


def _extract_text_from_messages(messages: list) -> str:
    """Extract the final AI text response from agent message history."""
    for msg in reversed(messages):
        if getattr(msg, "type", None) == "ai":
            content = getattr(msg, "content", "")
            if content and isinstance(content, str) and content.strip():
                return content
    return ""


class BaseAgent:
    """Abstract base for all CataLogA agents.

    Subclasses:
        - Set ``agent_name`` (class attr)
        - Set ``_SKILL_DIR`` (Path to skill prompt directory)
        - Implement ``build_user_message(**kwargs) -> str``
        - Optionally override ``run(state) -> dict``
    """

    agent_name: str = "BaseAgent"
    _SKILL_DIR: Path | None = None

    def __init__(self, config: Config):
        self.config = config
        self._llm = None        # lazy — simple LLM client
        self._tool_llm = None   # lazy — LLM client for tool-calling (thinking disabled)
        self._vendor = _detect_vendor(config.llm_base_url)

    @property
    def llm(self):
        """Simple LLM client (no tools).  Respects ``llm_thinking`` config."""
        if self._llm is None:
            self._llm = create_chat_openai(
                model=self.config.llm_model,
                api_key=self.config.llm_api_key,
                base_url=self.config.llm_base_url,
                temperature=self.config.llm_temperature,
                max_tokens=self.config.llm_max_tokens,
                thinking=self.config.llm_thinking,
            )
        return self._llm

    @property
    def tool_llm(self):
        """LLM client for tool-calling agents.  Thinking always disabled."""
        if self._tool_llm is None:
            self._tool_llm = create_chat_openai(
                model=self.config.llm_model,
                api_key=self.config.llm_api_key,
                base_url=self.config.llm_base_url,
                temperature=self.config.llm_temperature,
                max_tokens=self.config.llm_max_tokens,
                thinking="disabled",
            )
        return self._tool_llm

    # ── Skill loading ──────────────────────────────────────────

    def _skill_path(self, name: str) -> Path:
        if self._SKILL_DIR is None:
            raise NotImplementedError(
                f"{type(self).__name__} must set _SKILL_DIR"
            )
        return self._SKILL_DIR / (name if name.endswith(".md") else f"{name}.md")

    def load_skill(self, name: str = None) -> str:
        """Load a skill markdown file from _SKILL_DIR."""
        if name is None:
            name = self._resolve_default_skill()
        return self._skill_path(name).read_text(encoding="utf-8")

    def _resolve_default_skill(self) -> str:
        """Find the default skill file for this agent."""
        if hasattr(self, '_skill_file') and self._skill_file:
            if self._skill_path(self._skill_file).exists():
                return self._skill_file

        candidates = [
            f"{self.agent_name}_skill.md",
            f"{self.agent_name.upper()}_skill.md",
            f"{self.agent_name.lower()}.md",
        ]
        for name in candidates:
            if self._skill_path(name).exists():
                return name
        raise FileNotFoundError(
            f"No skill file found for {self.agent_name} in {self._SKILL_DIR}"
        )

    # ── Simple LLM invocation (no tools) ───────────────────────

    async def call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        parse_json: bool = True,
        max_retries: int = 3,
        retry_delay: int = 30,
        verbose: bool = False,
    ):
        """Invoke LLM with retry logic and optional JSON parsing.

        Set ``verbose=True`` to print the thinking chain (when thinking is
        enabled in config) to stdout.
        """
        from langchain_core.messages import SystemMessage, HumanMessage
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]

        for attempt in range(max_retries + 1):
            try:
                response = await self.llm.ainvoke(messages)
                raw = response.content

                # Print thinking chain if available and requested
                if verbose:
                    reasoning = (
                        response.additional_kwargs.get("reasoning_content")
                        if hasattr(response, "additional_kwargs")
                        else None
                    )
                    if reasoning:
                        print(f"\n{'='*60}\n[Thinking]\n{'='*60}")
                        print(reasoning)
                        print(f"{'='*60}\n[Answer]\n{'='*60}")

                return _parse_json(raw) if parse_json else raw
            except Exception as e:
                msg = str(e).lower()
                if attempt < max_retries and _is_retryable(msg):
                    logging.warning(f"LLM retry {attempt+1}/{max_retries}: {e}")
                    await asyncio.sleep(retry_delay)
                else:
                    raise

    # ── LangChain agent (tool-calling) ─────────────────────────

    def _create_agent(self, tools: list, system_prompt: str):
        """Create a LangChain tool-calling agent.

        Uses ``langchain.agents.create_agent`` with the tool_llm (thinking
        disabled to avoid reasoning_content passback issues).
        """
        from langchain.agents import create_agent as _create_agent
        return _create_agent(model=self.tool_llm, tools=tools, system_prompt=system_prompt)

    async def run_with_tools(
        self,
        user_message: str,
        tools: list,
        *,
        system_prompt: str = "",
        max_turns: int = 30,
        parse_json: bool = True,
        max_retries: int = 3,
        retry_delay: int = 180,
        log_prefix: str = "",
        stream_path: str = "",
    ):
        """Full tool-calling loop: create agent → invoke → continuation → result.

        Parameters
        ----------
        user_message : str
            The user prompt (from ``build_user_message()``).
        tools : list
            List of ``@tool``-decorated functions or LangChain BaseTool instances.
        system_prompt : str
            System prompt (typically from ``load_skill()``).
        max_turns : int
            ``recursion_limit`` for the agent.
        parse_json : bool
            Whether to parse the final text as JSON.
        max_retries : int
            HTTP-level retries for connection/timeout/rate-limit errors.
        retry_delay : int
            Seconds between retries.
        log_prefix : str
            Prefix for log messages.
        stream_path : str
            When ``llm_streaming=True``, write the ReAct log to this file.
            (also prints to stdout).

        Returns
        -------
        dict with keys:
            result : str or dict
                Final text output (parsed as JSON if possible).
            messages : list
                Full message history.
            tool_results : list
                Collected tool call + result pairs.
        """
        from langchain_core.messages import HumanMessage
        from .continuation import _is_truncated, run_continuation_ainvoke

        if not log_prefix:
            log_prefix = self.agent_name

        agent = self._create_agent(tools, system_prompt)
        config = {"recursion_limit": max_turns}

        # ── Agent execution (streaming or batch) ──────────────
        streaming = self.config.llm_streaming

        for attempt in range(max_retries + 1):
            try:
                if streaming:
                    messages = await self._invoke_streaming(
                        agent, user_message, config, log_prefix, stream_path,
                        system_prompt=system_prompt,
                    )
                else:
                    result = await agent.ainvoke(
                        {"messages": [HumanMessage(content=user_message)]},
                        config=config,
                    )
                    messages = result.get("messages", [])
                break
            except Exception as e:
                if attempt >= max_retries or not _is_retryable(str(e)):
                    raise
                logging.warning(
                    f"{log_prefix} HTTP retry {attempt+1}/{max_retries} "
                    f"in {retry_delay}s: {e}"
                )
                await asyncio.sleep(retry_delay)

        # ── Continuation loop ──────────────────────────────────
        messages = await run_continuation_ainvoke(
            agent, messages, config=config,
            continuation_prompt=(
                "Your previous response was truncated by the token limit. "
                "Continue EXACTLY from where you stopped. Do NOT repeat "
                "anything already written."
            ),
            max_attempts=3,
            log_prefix=log_prefix,
        )

        # ── Collect tool results ───────────────────────────────
        tool_results = []
        for i in range(1, len(messages)):
            prev = messages[i - 1]
            curr = messages[i]
            if getattr(curr, "type", None) == "tool":
                tool_call = None
                for tc in getattr(prev, "tool_calls", []) or []:
                    if tc.get("id") == getattr(curr, "tool_call_id", None):
                        tool_call = tc
                        break
                tool_results.append({
                    "name": getattr(curr, "name", "unknown"),
                    "args": tool_call.get("args", {}) if tool_call else {},
                    "result": getattr(curr, "content", ""),
                })

        raw_text = _extract_text_from_messages(messages)

        result_out = _parse_json(raw_text) if parse_json else raw_text
        if parse_json and isinstance(result_out, str):
            # Narrative followed by a fenced JSON block: _parse_json only
            # handles pure-JSON output, so fall back to block extraction.
            # Without this, downstream stages receive raw text instead of
            # the parsed verdict dict.
            result_out = _extract_json_block(raw_text) or result_out

        return {
            "result": result_out,
            "messages": messages,
            "tool_results": tool_results,
        }

    # ── Streaming agent invoke (prints ReAct loop) ──────────────

    async def _invoke_streaming(self, agent, user_message, config, prefix,
                                stream_path="", system_prompt=""):
        """Invoke agent with ``astream``, printing each ReAct turn to stdout
        and (if *stream_path* is set) writing a full audit log to a markdown file.

        The file includes system prompt, user message, and turn-by-turn LLM
        output + tool calls + tool results.
        """
        import json as _json
        from langchain_core.messages import HumanMessage

        _write = _log_writer(stream_path)
        _write(f"# {prefix} Audit Log\n\n", mode="w")

        # ── System prompt ────────────────────────────────────
        if system_prompt:
            _write("<details>\n<summary>System Prompt ({len} chars)</summary>\n\n"
                   .replace("{len}", str(len(system_prompt))))
            _write(system_prompt)
            _write("\n\n</details>\n\n")

        # ── User message ─────────────────────────────────────
        _write("<details>\n<summary>User Message ({len} chars)</summary>\n\n"
               .replace("{len}", str(len(user_message))))
        _write(user_message)
        _write("\n\n</details>\n\n")

        # ── ReAct log ────────────────────────────────────────
        _write("## ReAct Loop\n\n")

        messages = []
        turn = 0

        async for event in agent.astream(
            {"messages": [HumanMessage(content=user_message)]},
            config=config,
            stream_mode="updates",
        ):
            for _node_name, update in event.items():
                for msg in update.get("messages", []):
                    messages.append(msg)
                    msg_type = getattr(msg, "type", None)

                    if msg_type == "ai":
                        turn += 1
                        content = getattr(msg, "content", "")
                        tool_calls = getattr(msg, "tool_calls", None)
                        finish = msg.response_metadata.get("finish_reason", "")

                        header = f"\n### Turn {turn}\n"
                        _write(header)

                        if content and isinstance(content, str):
                            _write(f"{content}\n")
                            lines = content.strip().split("\n")
                            preview = lines[0] + ("..." if len(lines) > 1 else "")
                            print(f"\n{'─'*50}\n[Turn {turn}] {preview}", flush=True)
                        else:
                            print(f"\n{'─'*50}\n[Turn {turn}] (tool calls)", flush=True)

                        if tool_calls:
                            _write("\n**Tool calls:**\n\n")
                            for tc in tool_calls:
                                args_str = _json.dumps(tc.get("args", {}), ensure_ascii=False)
                                _write(f"- `{tc['name']}({args_str})`\n")
                                print(f"  🔧 {tc['name']}({args_str})", flush=True)

                        if finish == "stop" and not tool_calls:
                            print(f"  ✅ finish_reason=stop", flush=True)

                    elif msg_type == "tool":
                        name = getattr(msg, "name", "?")
                        result = getattr(msg, "content", "")
                        summary = result.replace("\n", " ")[:200]
                        _write(f"\n**{name}:**\n```\n{result[:2000]}\n```\n")
                        print(f"  📋 {name} → {summary}", flush=True)

        return messages


def _log_writer(path: str):
    """Return a callable that appends text to *path* (if set) else is a no-op."""
    if not path:
        return lambda content, mode="a": None
    import os as _os
    _os.makedirs(_os.path.dirname(path) or ".", exist_ok=True)
    def _write(content, mode="a"):
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)
    return _write

    # ── Subclass interface ─────────────────────────────────────

    def build_user_message(self, **kwargs) -> str:
        """Build the user prompt.  Subclasses MUST override."""
        raise NotImplementedError

    async def run(self, **kwargs) -> dict:
        """Template method: load skill → build message → call LLM.

        Subclasses can override to customize (e.g., to use run_with_tools).
        """
        skill = self.load_skill()
        user_msg = self.build_user_message(**kwargs)
        return await self.call_llm(skill, user_msg)
