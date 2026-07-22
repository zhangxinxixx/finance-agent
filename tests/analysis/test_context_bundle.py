from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from apps.analysis.context_bundle import (
    ContextBundleBudgetExceeded,
    assemble_context_bundle,
    select_incremental_evidence,
)


NOW = datetime(2026, 7, 22, 8, tzinfo=UTC)


def _evidence(
    source: str,
    evidence_id: str,
    *,
    business_time: datetime,
    ingested_at: datetime,
    payload: dict | None = None,
    session: str = "asia",
) -> dict:
    return {
        "source": source,
        "evidence_id": evidence_id,
        "business_time": business_time,
        "ingested_at": ingested_at,
        "session": session,
        "payload": payload or {"value": evidence_id},
        "source_ref": {"snapshot_id": evidence_id},
    }


def _bundle(**overrides):
    values = {
        "run_id": "run-67",
        "asset": "XAUUSD",
        "state_scope": "daily_close",
        "canonical_state_id": "state-66",
        "canonical_state": {
            "asset": "XAUUSD",
            "state_scope": "daily_close",
            "core_thesis": "等待突破",
            "key_levels": [4000, 4126],
        },
        "evidence": [
            _evidence(
                "market",
                "market-2",
                business_time=NOW,
                ingested_at=NOW + timedelta(minutes=2),
            )
        ],
        "evidence_cursors": {},
        "cutoff_at": NOW + timedelta(minutes=5),
        "assembled_at": NOW + timedelta(minutes=6),
        "facts": [{"figure_fact_id": "fact-1", "observation": "4000 上方承接"}],
        "expected_session": "asia",
    }
    values.update(overrides)
    return assemble_context_bundle(**values)


def test_bundle_is_stable_without_provider_conversation_metadata() -> None:
    with_transport = _evidence(
        "market",
        "market-2",
        business_time=NOW,
        ingested_at=NOW + timedelta(minutes=2),
        payload={
            "value": 4050,
            "provider": "jojocode",
            "conversation_id": "volatile-thread",
            "nested": {"thread_id": "thread-1"},
        },
    )
    clean = dict(with_transport)
    clean["payload"] = {"value": 4050, "nested": {}}

    first = _bundle(evidence=[with_transport])
    replay = _bundle(
        evidence=[clean],
        assembled_at=NOW + timedelta(hours=1),
    )

    assert replay.bundle_id == first.bundle_id
    assert replay.content_hash == first.content_hash
    assert "jojocode" not in first.model_dump_json()
    assert "volatile-thread" not in first.model_dump_json()


def test_per_source_cursor_keeps_late_business_evidence() -> None:
    cursors = {
        "market": {
            "ingested_at": NOW,
            "evidence_id": "market-1",
        },
        "macro": {
            "ingested_at": NOW,
            "evidence_id": "macro-5",
        },
    }
    evidence = [
        _evidence(
            "market",
            "market-2",
            business_time=NOW - timedelta(days=2),
            ingested_at=NOW + timedelta(minutes=1),
        ),
        _evidence(
            "macro",
            "macro-4",
            business_time=NOW + timedelta(minutes=1),
            ingested_at=NOW - timedelta(minutes=1),
        ),
    ]

    selected = select_incremental_evidence(
        evidence,
        cursors=cursors,
        cutoff_at=NOW + timedelta(minutes=5),
    )

    assert [item.evidence_id for item in selected] == ["market-2"]
    bundle = _bundle(evidence=evidence, evidence_cursors=cursors)
    assert bundle.next_evidence_cursors["market"].evidence_id == "market-2"
    assert bundle.next_evidence_cursors["macro"].evidence_id == "macro-5"


def test_history_bodies_are_omitted_but_lineage_and_summary_remain() -> None:
    bundle = _bundle(
        canonical_state={
            "asset": "XAUUSD",
            "state_scope": "daily_close",
            "one_line_conclusion": "维持等待",
            "previous_report": "不应进入 bundle" * 100,
            "previous_analysis_report": {"body": "过期日报正文" * 100},
            "weekly_anchor": {"body": "重复周报锚" * 100},
            "weekly_report_body": "完整周报正文" * 100,
            "input_snapshot_ids": {"weekly": "weekly-1"},
        }
    )
    payload = bundle.model_dump_json()

    assert "维持等待" in payload
    assert "weekly-1" in payload
    assert "完整周报正文" not in payload
    assert "过期日报正文" not in payload
    assert "重复周报锚" not in payload
    assert any(
        item["reason"].startswith("omitted_field:")
        for item in bundle.budget_trace.trim_reasons
    )


def test_budget_defers_newest_evidence_without_skipping_its_cursor() -> None:
    evidence = [
        _evidence(
            "news",
            f"news-{index}",
            business_time=NOW + timedelta(minutes=index),
            ingested_at=NOW + timedelta(minutes=index),
            payload={"text": "消息" * 500},
        )
        for index in range(1, 9)
    ]
    bundle = _bundle(evidence=evidence, facts=[], budget_tokens=1_600)
    retained = bundle.blocks[1].retained_evidence_ids

    assert bundle.budget_trace.within_budget is True
    assert bundle.budget_trace.estimated_tokens <= 1_600
    assert len(retained) < len(evidence)
    assert bundle.next_evidence_cursors["news"].evidence_id == retained[-1]
    assert any(
        item["reason"].startswith("budget_deferred:")
        for item in bundle.budget_trace.trim_reasons
    )
    deferred = select_incremental_evidence(
        evidence,
        cursors={"news": bundle.next_evidence_cursors["news"]},
        cutoff_at=NOW + timedelta(minutes=10),
    )
    assert [item.evidence_id for item in deferred] == [
        item["evidence_id"] for item in evidence[len(retained) :]
    ]


def test_budget_fails_closed_when_canonical_state_alone_is_too_large() -> None:
    with pytest.raises(ContextBundleBudgetExceeded) as exc_info:
        _bundle(
            canonical_state={
                "asset": "XAUUSD",
                "state_scope": "daily_close",
                "thesis": "x" * 2_000,
            },
            evidence=[],
            facts=[],
            budget_tokens=10,
        )

    assert exc_info.value.trace["within_budget"] is False


def test_session_and_business_time_alignment_are_explicit() -> None:
    bundle = _bundle(
        evidence=[
            _evidence(
                "market",
                "market-2",
                business_time=NOW,
                ingested_at=NOW + timedelta(minutes=1),
                session="asia",
            ),
            _evidence(
                "macro",
                "macro-2",
                business_time=NOW + timedelta(days=2),
                ingested_at=NOW + timedelta(minutes=2),
                session="us",
            ),
        ],
        max_alignment_seconds=3_600,
    )

    assert bundle.session["status"] == "mismatch"
    assert bundle.alignment["status"] == "misaligned"


def test_evidence_body_trim_is_recorded_and_naive_cutoff_is_rejected() -> None:
    bundle = _bundle(
        evidence=[
            _evidence(
                "news",
                "news-2",
                business_time=NOW,
                ingested_at=NOW + timedelta(minutes=1),
                payload={
                    "summary": "保留摘要",
                    "article_markdown": "不发送的完整正文" * 100,
                },
            )
        ]
    )

    assert "保留摘要" in bundle.model_dump_json()
    assert "不发送的完整正文" not in bundle.model_dump_json()
    assert {
        "block": "delta_evidence",
        "reason": "omitted_field:article_markdown",
    } in bundle.budget_trace.trim_reasons

    with pytest.raises(ValueError, match="timezone-aware"):
        select_incremental_evidence([], cursors={}, cutoff_at=datetime(2026, 7, 22, 8))


def test_bundle_rejects_forged_budget_metrics() -> None:
    bundle = _bundle()
    payload = bundle.model_dump(mode="json")
    payload["blocks"][0]["estimated_tokens"] = 0

    with pytest.raises(ValidationError, match="estimated_tokens"):
        type(bundle).model_validate(payload)


def test_scope_is_part_of_bundle_hash_and_identity() -> None:
    daily = _bundle()
    intraday = _bundle(
        state_scope="intraday",
        canonical_state={
            "asset": "XAUUSD",
            "state_scope": "intraday",
            "core_thesis": "等待突破",
            "key_levels": [4000, 4126],
        },
    )

    assert daily.schema_version == "analysis_context_bundle.v2"
    assert daily.state_scope == "daily_close"
    assert intraday.state_scope == "intraday"
    assert intraday.content_hash != daily.content_hash
    assert intraday.bundle_id != daily.bundle_id


def test_bundle_rejects_cross_scope_canonical_state() -> None:
    with pytest.raises(ValueError, match="different state_scope"):
        _bundle(state_scope="intraday")
