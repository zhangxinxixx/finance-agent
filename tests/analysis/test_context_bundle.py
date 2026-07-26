from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from apps.analysis.context_bundle import (
    ContextBundleBudgetExceeded,
    assemble_context_bundle,
    select_incremental_evidence,
)
from apps.analysis.context_bundle.schemas import AnalysisContextBundle, compute_bundle_content_hash
from apps.analysis.context_bundle.selection import EvidenceSelectionBudgetError
from apps.analysis.evidence_delta import evaluate_evidence_delta


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
    material_payload = {
        "evidence_type": "material_event",
        "asset": "XAUUSD",
        "source_quality": "official",
        "event_id": evidence_id,
        "cluster_key": f"cluster:{source}:{evidence_id}",
        "event_type": "test_event",
        "claim": evidence_id,
        "materiality_score": 10,
        "risk_level": "low",
        "recompute_eligible": False,
        "confirmation_status": "confirmed",
        "metadata": payload or {},
    }
    return {
        "source": source,
        "evidence_id": evidence_id,
        "business_time": business_time,
        "ingested_at": ingested_at,
        "session": session,
        "payload": material_payload,
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
    clean = _evidence(
        "market",
        "market-2",
        business_time=NOW,
        ingested_at=NOW + timedelta(minutes=2),
        payload={"value": 4050, "nested": {}},
    )

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


def test_budget_keeps_newest_evidence_without_advancing_across_oldest_gap() -> None:
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
    assert retained[0] == "news-5"
    assert "news" not in bundle.next_evidence_cursors
    assert bundle.deferred_queue[0]["evidence_id"] == "news-1"
    assert any(
        item["reason"].startswith("budget_deferred:")
        for item in bundle.budget_trace.trim_reasons
    )
    assert bundle.processed_above_frontier["news"]
    assert {item["snapshot_id"] for item in bundle.source_refs} == {
        f"news-{index}" for index in range(1, 6)
    }


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

    assert daily.schema_version == "analysis_context_bundle.v3"
    assert daily.state_scope == "daily_close"
    assert intraday.state_scope == "intraday"
    assert intraday.content_hash != daily.content_hash
    assert intraday.bundle_id != daily.bundle_id


def test_bundle_rejects_cross_scope_canonical_state() -> None:
    with pytest.raises(ValueError, match="different state_scope"):
        _bundle(state_scope="intraday")


def test_v3_requires_identity_bound_decision_and_normalizes_selection_order() -> None:
    bundle = _bundle(
        evidence=[
            _evidence(
                "news",
                "news-2",
                business_time=NOW,
                ingested_at=NOW + timedelta(minutes=2),
            ),
            _evidence(
                "market",
                "market-2",
                business_time=NOW,
                ingested_at=NOW + timedelta(minutes=1),
            ),
        ]
    )
    payload = bundle.model_dump(mode="json")
    payload["selection_decisions"] = list(reversed(payload["selection_decisions"]))
    canonical = dict(payload)
    canonical["selection_decisions"] = sorted(
        canonical["selection_decisions"],
        key=lambda item: (item["source"], item["evidence_id"], item["outcome"]),
    )
    canonical["content_hash"] = compute_bundle_content_hash(canonical)
    canonical["bundle_id"] = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"finance-agent:context-bundle:{canonical['content_hash']}",
        )
    )
    payload["content_hash"] = canonical["content_hash"]
    payload["bundle_id"] = canonical["bundle_id"]

    normalized = AnalysisContextBundle.model_validate(payload)
    assert normalized.selection_decisions == canonical["selection_decisions"]
    assert compute_bundle_content_hash(payload) == bundle.content_hash
    replay = _bundle(evidence=list(reversed([
        _evidence(
            "news",
            "news-2",
            business_time=NOW,
            ingested_at=NOW + timedelta(minutes=2),
        ),
        _evidence(
            "market",
            "market-2",
            business_time=NOW,
            ingested_at=NOW + timedelta(minutes=1),
        ),
    ])))
    assert replay.content_hash == bundle.content_hash
    assert replay.bundle_id == bundle.bundle_id

    missing = bundle.model_dump(mode="json")
    missing["evidence_delta_decision"] = None
    missing["content_hash"] = compute_bundle_content_hash(missing)
    missing["bundle_id"] = str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"finance-agent:context-bundle:{missing['content_hash']}")
    )
    with pytest.raises(ValidationError, match="requires decision"):
        AnalysisContextBundle.model_validate(missing)

    mismatched = bundle.model_dump(mode="json")
    other = evaluate_evidence_delta(
        asset="GC",
        state_scope="daily_close",
        canonical_state_id=bundle.canonical_state_id,
        evidence=[],
    )
    mismatched["evidence_delta_decision"] = other.model_dump(mode="json")
    mismatched["content_hash"] = compute_bundle_content_hash(mismatched)
    mismatched["bundle_id"] = str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"finance-agent:context-bundle:{mismatched['content_hash']}",
        )
    )
    with pytest.raises(ValidationError, match="identity does not match"):
        AnalysisContextBundle.model_validate(mismatched)


def test_v3_rejects_forged_selection_counts_and_non_strict_sla() -> None:
    bundle = _bundle()
    forged = bundle.model_dump(mode="json")
    forged["selection_trace"]["retained_count"] += 1
    forged["content_hash"] = compute_bundle_content_hash(forged)
    forged["bundle_id"] = str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"finance-agent:context-bundle:{forged['content_hash']}")
    )
    with pytest.raises(ValidationError, match="trace counts"):
        AnalysisContextBundle.model_validate(forged)

    boolean_sla = bundle.model_dump(mode="json")
    boolean_sla["freshness_sla_seconds"] = {"market": True}
    with pytest.raises(ValidationError):
        AnalysisContextBundle.model_validate(boolean_sla)


def test_manual_review_evidence_is_mandatory_and_budget_failure_is_explicit() -> None:
    evidence = _evidence(
        "macro",
        "macro-conflict",
        business_time=NOW,
        ingested_at=NOW + timedelta(minutes=1),
    )
    evidence["payload"] = {
        "evidence_type": "macro_metric",
        "asset": "XAUUSD",
        "source_quality": "unverified",
        "metric": "dxy",
        "current_value": 101.0,
        "previous_value": 100.0,
        "unit": "index",
        "metadata": {"detail": "x" * 1_500},
    }

    with pytest.raises(EvidenceSelectionBudgetError, match="mandatory evidence exceeds"):
        _bundle(evidence=[evidence], facts=[], budget_tokens=500)


def test_freshness_and_session_use_pretrim_eligible_evidence() -> None:
    asia = _evidence(
        "market",
        "market-large",
        business_time=NOW,
        ingested_at=NOW + timedelta(minutes=1),
        payload={"detail": "a" * 1_200},
        session="asia",
    )
    us = _evidence(
        "macro",
        "macro-large",
        business_time=NOW + timedelta(hours=2),
        ingested_at=NOW + timedelta(minutes=2),
        payload={"detail": "b" * 1_200},
        session="us",
    )
    bundle = _bundle(
        evidence=[asia, us],
        facts=[],
        budget_tokens=850,
        freshness_sla_seconds={"macro": 60},
        default_freshness_sla_seconds=60,
        max_alignment_seconds=60,
    )

    assert bundle.selection_trace["deferred_count"] > 0
    assert set(bundle.freshness) == {"macro", "market"}
    assert bundle.freshness["market"]["sla_policy"] == "default"
    assert bundle.session["status"] == "mismatch"
    assert bundle.alignment["status"] == "misaligned"
