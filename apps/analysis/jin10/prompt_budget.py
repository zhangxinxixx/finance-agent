from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


DEFAULT_PROMPT_TOKEN_BUDGET = 15_000
PROMPT_BUDGET_SCHEMA_VERSION = "jin10-prompt-budget-v1"
_SECTION_PATTERN = re.compile(r"(?m)^=== (?P<name>.+?) ===\n")


class PromptBudgetExceeded(ValueError):
    """Raised before an LLM call when deterministic prompt trimming is insufficient."""

    def __init__(self, trace: dict[str, Any]) -> None:
        total = (trace.get("total") or {}).get("estimated_tokens")
        budget = trace.get("budget_tokens")
        super().__init__(f"jin10 prompt budget exceeded: estimated_tokens={total}; budget={budget}")
        self.trace = trace


def estimate_prompt_tokens(value: str) -> int:
    """Return a deterministic, conservative estimate for mixed Chinese/English text.

    The legacy reports are predominantly Chinese.  Three UTF-8 bytes per token
    tracks the observed request usage more closely than the usual English-only
    four-characters-per-token shortcut and intentionally errs on the safe side.
    """

    if not value:
        return 0
    return (len(value.encode("utf-8")) + 2) // 3


def deterministic_trim_text(
    value: str,
    *,
    max_chars: int,
    block_name: str,
    reason: str,
    trim_reasons: dict[str, list[str]],
) -> str:
    """Bound free text using a stable head/tail window and record why it changed."""

    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    marker = f"\n...[deterministic trim: omitted_chars={omitted}; reason={reason}]...\n"
    available = max(0, max_chars - len(marker))
    head_chars = int(available * 0.75)
    tail_chars = available - head_chars
    trimmed = f"{text[:head_chars]}{marker}{text[-tail_chars:] if tail_chars else ''}"
    trim_reasons.setdefault(block_name, []).append(reason)
    return trimmed


def build_prompt_budget_trace(
    prompt: str,
    *,
    trim_reasons: Mapping[str, list[str]] | None = None,
    budget_tokens: int = DEFAULT_PROMPT_TOKEN_BUDGET,
) -> dict[str, Any]:
    """Measure the complete prompt and every explicit ``=== block ===`` section."""

    reasons = trim_reasons or {}
    blocks: list[dict[str, Any]] = []
    matches = list(_SECTION_PATTERN.finditer(prompt))
    if not matches:
        blocks.append(_block_metrics("prompt", prompt, reasons.get("prompt") or []))
    else:
        preamble = prompt[: matches[0].start()]
        if preamble:
            blocks.append(_block_metrics("instructions", preamble, reasons.get("instructions") or []))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(prompt)
            name = match.group("name")
            blocks.append(_block_metrics(name, prompt[match.start() : end], reasons.get(name) or []))

    total = _text_metrics(prompt)
    return {
        "schema_version": PROMPT_BUDGET_SCHEMA_VERSION,
        "budget_tokens": budget_tokens,
        "within_budget": total["estimated_tokens"] <= budget_tokens,
        "total": total,
        "blocks": blocks,
        "trim_reasons": [
            {"block": name, "reason": reason} for name in sorted(reasons) for reason in dict.fromkeys(reasons[name])
        ],
    }


def enforce_prompt_budget(
    prompt: str,
    *,
    trim_reasons: Mapping[str, list[str]] | None = None,
    budget_tokens: int = DEFAULT_PROMPT_TOKEN_BUDGET,
) -> dict[str, Any]:
    """Return the trace or fail closed; never substitute the unbounded prompt."""

    trace = build_prompt_budget_trace(
        prompt,
        trim_reasons=trim_reasons,
        budget_tokens=budget_tokens,
    )
    if not trace["within_budget"]:
        raise PromptBudgetExceeded(trace)
    return trace


def _block_metrics(name: str, value: str, trim_reasons: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        **_text_metrics(value),
        "trim_reasons": list(dict.fromkeys(trim_reasons)),
    }


def _text_metrics(value: str) -> dict[str, int]:
    return {
        "chars": len(value),
        "utf8_bytes": len(value.encode("utf-8")),
        "estimated_tokens": estimate_prompt_tokens(value),
    }
