from __future__ import annotations

import pytest

from apps.analysis.jin10.prompt_budget import (
    PromptBudgetExceeded,
    build_prompt_budget_trace,
    deterministic_trim_text,
    enforce_prompt_budget,
    estimate_prompt_tokens,
)


def test_prompt_budget_trace_records_blocks_and_trim_reasons() -> None:
    reasons = {"analysis_baseline": ["single_effective_baseline"]}
    prompt = "说明\n=== analysis_baseline ===\n基准\n=== latest_market ===\n市场\n"

    trace = build_prompt_budget_trace(prompt, trim_reasons=reasons, budget_tokens=100)

    assert trace["within_budget"] is True
    assert trace["total"]["estimated_tokens"] == estimate_prompt_tokens(prompt)
    assert [item["name"] for item in trace["blocks"]] == [
        "instructions",
        "analysis_baseline",
        "latest_market",
    ]
    assert trace["blocks"][1]["trim_reasons"] == ["single_effective_baseline"]


def test_deterministic_trim_is_stable_and_auditable() -> None:
    reasons: dict[str, list[str]] = {}

    first = deterministic_trim_text(
        "0123456789" * 100,
        max_chars=120,
        block_name="article",
        reason="raw_article_text_limited",
        trim_reasons=reasons,
    )
    second = deterministic_trim_text(
        "0123456789" * 100,
        max_chars=120,
        block_name="article",
        reason="raw_article_text_limited",
        trim_reasons={},
    )

    assert first == second
    assert len(first) == 120
    assert "omitted_chars=880" in first
    assert reasons == {"article": ["raw_article_text_limited"]}


def test_prompt_budget_fails_closed_when_limit_is_exceeded() -> None:
    prompt = "中文" * 200

    with pytest.raises(PromptBudgetExceeded) as exc_info:
        enforce_prompt_budget(prompt, budget_tokens=10)

    assert exc_info.value.trace["within_budget"] is False
    assert exc_info.value.trace["total"]["estimated_tokens"] > 10
