"""Truncation detection and continuation loop.

Ported from FORMA ``harness/continuation.py``.  When the LLM output is
truncated by the token limit (``finish_reason == "length"``), we ask the
model to continue from where it stopped.

Only the async ``ainvoke`` path is ported; streaming and sync paths can be
added later when needed.
"""

import logging

from langchain_core.messages import HumanMessage


def _find_last_ai_message(messages: list):
    """Return the last AI message, skipping tool messages."""
    for msg in reversed(messages):
        if getattr(msg, "type", None) == "ai":
            return msg
    return None


def _is_truncated(messages: list, *, since: int = 0) -> bool:
    """Check whether any AI message was truncated by max_tokens.

    Scans ALL AI messages (not just the last one) because in multi-turn
    tool-calling agents, truncation may happen in an intermediate turn
    while the final turn completes normally.
    """
    for msg in reversed(messages[since:]):
        if getattr(msg, "type", None) == "ai":
            if msg.response_metadata.get("finish_reason") == "length":
                return True
    return False


_STALE_PROMPT = (
    "STILL truncated. Continue DIRECTLY from the last character. "
    "Do NOT repeat or explain — output ONLY the remaining content."
)


async def run_continuation_ainvoke(
    agent,
    messages: list,
    *,
    config: dict,
    continuation_prompt: str = "",
    max_attempts: int = 3,
    log_prefix: str = "",
) -> list:
    """Run the truncation-continuation loop using ``agent.ainvoke``.

    Appends continuation messages to *messages* in-place.

    Returns the mutated *messages* list.
    """
    ctn_attempt = 0
    n_before = len(messages)

    while _is_truncated(messages, since=n_before) and ctn_attempt < max_attempts:
        ctn_attempt += 1
        logging.warning(
            f"{log_prefix} output truncated, "
            f"continuation attempt {ctn_attempt}/{max_attempts}..."
        )
        try:
            continuation_msgs = list(messages)
            prompt = continuation_prompt if ctn_attempt == 1 else _STALE_PROMPT
            continuation_msgs.append(HumanMessage(content=prompt))
            result = await agent.ainvoke(
                {"messages": continuation_msgs}, config=config
            )
            result_msgs = result.get("messages", [])
            new_msgs = result_msgs[len(continuation_msgs):]
            messages.extend(new_msgs)
            n_before = len(messages) - len(new_msgs)
            logging.info(
                f"{log_prefix} continuation {ctn_attempt} completed."
            )
        except Exception as exc:
            logging.warning(
                f"{log_prefix} continuation {ctn_attempt} failed: {exc}. "
                "Returning truncated result."
            )
            break

    if _is_truncated(messages, since=n_before):
        logging.error(
            f"{log_prefix} STILL TRUNCATED after {ctn_attempt} "
            "continuation(s) — output may be incomplete."
        )

    return messages
