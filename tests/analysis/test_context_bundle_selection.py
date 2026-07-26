from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from apps.analysis.context_bundle.selection import (
    DeferredEvidencePointer,
    EvidencePriority,
    EvidencePriorityClass,
    EvidenceSelectionBudgetError,
    EvidenceSelectionStateError,
    select_material_evidence,
)


NOW = datetime(2026, 7, 22, 8, tzinfo=UTC)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _evidence(
    source: str,
    evidence_id: str,
    *,
    minute: int,
) -> dict:
    observed_at = NOW + timedelta(minutes=minute)
    return {
        "source": source,
        "evidence_id": evidence_id,
        "business_time": observed_at,
        "ingested_at": observed_at,
        "session": "asia",
        "payload": {"value": evidence_id},
        "source_ref": {"snapshot_id": evidence_id},
    }


def _priority(
    source: str,
    evidence_id: str,
    *,
    priority_class: EvidencePriorityClass,
    tokens: int,
    mandatory: bool = False,
    semantic_hash: str | None = None,
) -> EvidencePriority:
    return EvidencePriority(
        source=source,
        evidence_id=evidence_id,
        semantic_hash=semantic_hash or _hash(evidence_id),
        priority_class=priority_class,
        materiality="critical" if mandatory else "caller_confirmed",
        mandatory=mandatory,
        reason_codes=(f"priority:{priority_class.value}",),
        estimated_tokens=tokens,
    )


def _select(
    *,
    evidence: list[dict],
    priorities: list[EvidencePriority],
    budget_tokens: int,
    cursors: dict | None = None,
    deferred_queue: tuple[DeferredEvidencePointer, ...] = (),
    processed_above_frontier: dict[str, tuple[DeferredEvidencePointer, ...]] | None = None,
):
    return select_material_evidence(
        evidence=evidence,
        priorities=priorities,
        evidence_cursors=cursors or {},
        cutoff_at=NOW + timedelta(minutes=30),
        evidence_budget_tokens=budget_tokens,
        deferred_queue=deferred_queue,
        processed_above_frontier=processed_above_frontier or {},
    )


def test_critical_evidence_crosses_backlog_without_advancing_past_gap() -> None:
    evidence = [
        _evidence("news", "backlog", minute=1),
        _evidence("news", "critical", minute=2),
    ]
    priorities = [
        _priority(
            "news",
            "backlog",
            priority_class=EvidencePriorityClass.BACKLOG,
            tokens=8,
        ),
        _priority(
            "news",
            "critical",
            priority_class=EvidencePriorityClass.CONFIRMED_INVALIDATION,
            tokens=2,
        ),
    ]
    cursor = {"news": {"ingested_at": NOW, "evidence_id": "seed"}}

    result = _select(
        evidence=evidence,
        priorities=priorities,
        budget_tokens=2,
        cursors=cursor,
    )

    assert result.retained_evidence_ids == ("critical",)
    assert [item.evidence_id for item in result.deferred_queue] == ["backlog"]
    assert result.next_evidence_cursors["news"].evidence_id == "seed"
    assert [
        item.evidence_id for item in result.processed_above_frontier["news"]
    ] == ["critical"]


def test_processed_above_frontier_does_not_consume_budget_or_trigger_again() -> None:
    first = _select(
        evidence=[
            _evidence("news", "backlog", minute=1),
            _evidence("news", "critical", minute=2),
        ],
        priorities=[
            _priority(
                "news",
                "backlog",
                priority_class=EvidencePriorityClass.BACKLOG,
                tokens=8,
            ),
            _priority(
                "news",
                "critical",
                priority_class=EvidencePriorityClass.CONFIRMED_INVALIDATION,
                tokens=2,
            ),
        ],
        budget_tokens=2,
        cursors={"news": {"ingested_at": NOW, "evidence_id": "seed"}},
    )

    replay = _select(
        evidence=[
            _evidence("news", "critical", minute=2),
            _evidence("news", "backlog", minute=1),
        ],
        priorities=[
            _priority(
                "news",
                "critical",
                priority_class=EvidencePriorityClass.CONFIRMED_INVALIDATION,
                tokens=2,
            ),
            _priority(
                "news",
                "backlog",
                priority_class=EvidencePriorityClass.BACKLOG,
                tokens=8,
            ),
        ],
        budget_tokens=1,
        cursors={"news": {"ingested_at": NOW, "evidence_id": "seed"}},
        deferred_queue=first.deferred_queue,
        processed_above_frontier=first.processed_above_frontier,
    )

    assert replay.retained_evidence_ids == ()
    assert replay.trace.retained_tokens == 0
    assert any(
        item.evidence_id == "critical"
        and item.outcome == "rejected"
        and "already_processed_above_frontier" in item.reasons
        for item in replay.decisions
    )


def test_filling_gap_absorbs_processed_items_and_advances_frontier() -> None:
    evidence = [
        _evidence("news", "backlog", minute=1),
        _evidence("news", "critical", minute=2),
    ]
    priorities = [
        _priority(
            "news",
            "backlog",
            priority_class=EvidencePriorityClass.BACKLOG,
            tokens=8,
        ),
        _priority(
            "news",
            "critical",
            priority_class=EvidencePriorityClass.CONFIRMED_INVALIDATION,
            tokens=2,
        ),
    ]
    cursor = {"news": {"ingested_at": NOW, "evidence_id": "seed"}}
    first = _select(
        evidence=evidence,
        priorities=priorities,
        budget_tokens=2,
        cursors=cursor,
    )

    resolved = _select(
        evidence=evidence,
        priorities=priorities,
        budget_tokens=8,
        cursors=cursor,
        deferred_queue=first.deferred_queue,
        processed_above_frontier=first.processed_above_frontier,
    )

    assert resolved.retained_evidence_ids == ("backlog",)
    assert resolved.next_evidence_cursors["news"].evidence_id == "critical"
    assert resolved.deferred_queue == ()
    assert resolved.processed_above_frontier == {}


def test_frontiers_are_isolated_per_source() -> None:
    result = _select(
        evidence=[
            _evidence("news", "news-backlog", minute=1),
            _evidence("news", "news-critical", minute=2),
            _evidence("market", "market-current", minute=3),
        ],
        priorities=[
            _priority(
                "news",
                "news-backlog",
                priority_class=EvidencePriorityClass.BACKLOG,
                tokens=9,
            ),
            _priority(
                "news",
                "news-critical",
                priority_class=EvidencePriorityClass.CONFIRMED_INVALIDATION,
                tokens=1,
            ),
            _priority(
                "market",
                "market-current",
                priority_class=EvidencePriorityClass.ORDINARY_CURRENT,
                tokens=1,
            ),
        ],
        budget_tokens=2,
        cursors={
            "news": {"ingested_at": NOW, "evidence_id": "news-seed"},
            "market": {"ingested_at": NOW, "evidence_id": "market-seed"},
        },
    )

    assert result.next_evidence_cursors["news"].evidence_id == "news-seed"
    assert result.next_evidence_cursors["market"].evidence_id == "market-current"
    assert [
        item.evidence_id for item in result.processed_above_frontier["news"]
    ] == ["news-critical"]
    assert "market" not in result.processed_above_frontier


def test_same_timestamp_uses_evidence_id_as_stable_frontier_order() -> None:
    evidence = [
        _evidence("news", "b", minute=1),
        _evidence("news", "a", minute=1),
    ]
    priorities = [
        _priority(
            "news",
            "b",
            priority_class=EvidencePriorityClass.ORDINARY_CURRENT,
            tokens=1,
        ),
        _priority(
            "news",
            "a",
            priority_class=EvidencePriorityClass.ORDINARY_CURRENT,
            tokens=1,
        ),
    ]

    result = _select(evidence=evidence, priorities=priorities, budget_tokens=1)

    assert result.retained_evidence_ids == ("a",)
    assert [item.evidence_id for item in result.deferred_queue] == ["b"]
    assert result.next_evidence_cursors["news"].evidence_id == "a"


def test_evidence_after_cutoff_is_rejected_and_never_queued() -> None:
    result = select_material_evidence(
        evidence=[_evidence("news", "future", minute=31)],
        priorities=[
            _priority(
                "news",
                "future",
                priority_class=EvidencePriorityClass.CONFIRMED_INVALIDATION,
                tokens=1,
            )
        ],
        evidence_cursors={},
        cutoff_at=NOW + timedelta(minutes=30),
        evidence_budget_tokens=10,
    )

    assert result.retained_evidence_ids == ()
    assert result.deferred_queue == ()
    assert result.processed_above_frontier == {}
    assert result.next_evidence_cursors == {}
    assert result.decisions[0].reasons == ("after_cutoff",)


def test_mandatory_evidence_over_budget_fails_closed() -> None:
    with pytest.raises(EvidenceSelectionBudgetError) as exc_info:
        _select(
            evidence=[_evidence("macro", "must-keep", minute=1)],
            priorities=[
                _priority(
                    "macro",
                    "must-keep",
                    priority_class=EvidencePriorityClass.MANDATORY_CRITICAL,
                    tokens=5,
                    mandatory=True,
                )
            ],
            budget_tokens=4,
        )

    assert exc_info.value.required_tokens == 5
    assert exc_info.value.budget_tokens == 4
    assert exc_info.value.mandatory_evidence_ids == ("must-keep",)
    assert [
        (item.source, item.evidence_id)
        for item in exc_info.value.mandatory_evidence_keys
    ] == [("macro", "must-keep")]


def test_deferred_queue_hash_conflict_fails_before_frontier_advances() -> None:
    cursor = {"news": {"ingested_at": NOW, "evidence_id": "seed"}}
    corrupted = DeferredEvidencePointer(
        source="news",
        evidence_id="queued",
        ingested_at=NOW + timedelta(minutes=1),
        semantic_hash=_hash("old-content"),
    )

    with pytest.raises(EvidenceSelectionStateError, match="semantic_hash"):
        _select(
            evidence=[_evidence("news", "queued", minute=1)],
            priorities=[
                _priority(
                    "news",
                    "queued",
                    priority_class=EvidencePriorityClass.BACKLOG,
                    tokens=1,
                    semantic_hash=_hash("changed-content"),
                )
            ],
            budget_tokens=1,
            cursors=cursor,
            deferred_queue=(corrupted,),
        )

    assert cursor["news"]["evidence_id"] == "seed"


def test_processed_pointer_hash_conflict_fails_even_without_replayed_body() -> None:
    processed = DeferredEvidencePointer(
        source="news",
        evidence_id="already-used",
        ingested_at=NOW + timedelta(minutes=2),
        semantic_hash=_hash("original"),
    )

    with pytest.raises(EvidenceSelectionStateError, match="processed semantic_hash"):
        _select(
            evidence=[_evidence("news", "gap", minute=1)],
            priorities=[
                _priority(
                    "news",
                    "gap",
                    priority_class=EvidencePriorityClass.BACKLOG,
                    tokens=1,
                ),
                _priority(
                    "news",
                    "already-used",
                    priority_class=EvidencePriorityClass.CONFIRMED_INVALIDATION,
                    tokens=1,
                    semantic_hash=_hash("mutated"),
                ),
            ],
            budget_tokens=1,
            processed_above_frontier={"news": (processed,)},
        )


def test_persisted_deferred_wins_same_class_to_prevent_starvation() -> None:
    old = _evidence("news", "old", minute=1)
    old_priority = _priority(
        "news",
        "old",
        priority_class=EvidencePriorityClass.ORDINARY_CURRENT,
        tokens=1,
    )
    first = _select(
        evidence=[old],
        priorities=[old_priority],
        budget_tokens=0,
    )

    assert first.deferred_queue[0].deferred_priority_class is EvidencePriorityClass.ORDINARY_CURRENT
    assert "evidence_budget_exhausted" in first.deferred_queue[0].deferral_reasons

    second = _select(
        evidence=[_evidence("news", "new", minute=2), old],
        priorities=[
            _priority(
                "news",
                "new",
                priority_class=EvidencePriorityClass.ORDINARY_CURRENT,
                tokens=1,
            ),
            old_priority,
        ],
        budget_tokens=1,
        deferred_queue=first.deferred_queue,
    )

    assert second.retained_evidence_ids == ("old",)
    assert [item.evidence_id for item in second.deferred_queue] == ["new"]
    assert second.next_evidence_cursors["news"].evidence_id == "old"


def test_higher_priority_new_evidence_can_still_cross_persisted_gap() -> None:
    old = _evidence("news", "old", minute=1)
    old_priority = _priority(
        "news",
        "old",
        priority_class=EvidencePriorityClass.BACKLOG,
        tokens=1,
    )
    first = _select(evidence=[old], priorities=[old_priority], budget_tokens=0)

    second = _select(
        evidence=[old, _evidence("news", "critical", minute=2)],
        priorities=[
            old_priority,
            _priority(
                "news",
                "critical",
                priority_class=EvidencePriorityClass.CONFIRMED_INVALIDATION,
                tokens=1,
            ),
        ],
        budget_tokens=1,
        deferred_queue=first.deferred_queue,
    )

    assert second.retained_evidence_ids == ("critical",)
    assert [item.evidence_id for item in second.deferred_queue] == ["old"]
    assert [
        item.evidence_id for item in second.processed_above_frontier["news"]
    ] == ["critical"]


def test_deferred_priority_snapshot_does_not_block_next_round_reclassification() -> None:
    item = _evidence("news", "reclassified", minute=1)
    first = _select(
        evidence=[item],
        priorities=[
            _priority(
                "news",
                "reclassified",
                priority_class=EvidencePriorityClass.BACKLOG,
                tokens=1,
            )
        ],
        budget_tokens=0,
    )

    second = _select(
        evidence=[item],
        priorities=[
            _priority(
                "news",
                "reclassified",
                priority_class=EvidencePriorityClass.CONFIRMED_KEY_LEVEL,
                tokens=1,
            )
        ],
        budget_tokens=1,
        deferred_queue=first.deferred_queue,
    )

    assert first.deferred_queue[0].deferred_priority_class is EvidencePriorityClass.BACKLOG
    assert second.retained_evidence_ids == ("reclassified",)


@pytest.mark.parametrize(
    ("priority_class", "mandatory"),
    [
        (EvidencePriorityClass.MANDATORY_CRITICAL, False),
        (EvidencePriorityClass.CONFIRMED_INVALIDATION, True),
    ],
)
def test_mandatory_flag_and_priority_class_must_agree(
    priority_class: EvidencePriorityClass,
    mandatory: bool,
) -> None:
    with pytest.raises(ValidationError, match="mandatory must be true exactly"):
        _priority(
            "macro",
            "invalid-mandatory",
            priority_class=priority_class,
            tokens=1,
            mandatory=mandatory,
        )


def test_unrelated_extra_priority_fails_closed() -> None:
    with pytest.raises(EvidenceSelectionStateError, match="no current or processed evidence"):
        _select(
            evidence=[_evidence("news", "current", minute=1)],
            priorities=[
                _priority(
                    "news",
                    "current",
                    priority_class=EvidencePriorityClass.ORDINARY_CURRENT,
                    tokens=1,
                ),
                _priority(
                    "news",
                    "unrelated",
                    priority_class=EvidencePriorityClass.BACKLOG,
                    tokens=1,
                ),
            ],
            budget_tokens=1,
        )


def test_selection_is_deterministic_across_input_order() -> None:
    evidence = [
        _evidence("news", "ordinary", minute=1),
        _evidence("market", "regime", minute=2),
        _evidence("macro", "invalidation", minute=3),
    ]
    priorities = [
        _priority(
            "news",
            "ordinary",
            priority_class=EvidencePriorityClass.ORDINARY_CURRENT,
            tokens=1,
        ),
        _priority(
            "market",
            "regime",
            priority_class=EvidencePriorityClass.MARKET_OPTIONS_REGIME,
            tokens=1,
        ),
        _priority(
            "macro",
            "invalidation",
            priority_class=EvidencePriorityClass.CONFIRMED_INVALIDATION,
            tokens=1,
        ),
    ]

    first = _select(evidence=evidence, priorities=priorities, budget_tokens=2)
    second = _select(
        evidence=list(reversed(evidence)),
        priorities=list(reversed(priorities)),
        budget_tokens=2,
    )

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_same_evidence_id_from_different_sources_keeps_source_aware_identity() -> None:
    result = _select(
        evidence=[
            _evidence("news", "shared-id", minute=1),
            _evidence("market", "shared-id", minute=2),
        ],
        priorities=[
            _priority(
                "news",
                "shared-id",
                priority_class=EvidencePriorityClass.ORDINARY_CURRENT,
                tokens=1,
                semantic_hash=_hash("news/shared-id"),
            ),
            _priority(
                "market",
                "shared-id",
                priority_class=EvidencePriorityClass.ORDINARY_CURRENT,
                tokens=1,
                semantic_hash=_hash("market/shared-id"),
            ),
        ],
        budget_tokens=2,
    )

    assert result.retained_evidence_ids == ("shared-id", "shared-id")
    assert {
        (item.source, item.evidence_id) for item in result.retained_evidence_keys
    } == {("news", "shared-id"), ("market", "shared-id")}


def test_missing_priority_fails_closed_instead_of_assuming_low_priority() -> None:
    with pytest.raises(EvidenceSelectionStateError, match="missing evidence priority"):
        _select(
            evidence=[_evidence("news", "unclassified", minute=1)],
            priorities=[],
            budget_tokens=1,
        )


def test_identical_duplicates_are_deduplicated_but_evidence_conflicts_fail() -> None:
    item = _evidence("news", "duplicate", minute=1)
    priority = _priority(
        "news",
        "duplicate",
        priority_class=EvidencePriorityClass.ORDINARY_CURRENT,
        tokens=1,
    )
    deduplicated = _select(
        evidence=[item, dict(item)],
        priorities=[priority, priority.model_copy()],
        budget_tokens=1,
    )

    assert deduplicated.retained_evidence_ids == ("duplicate",)

    conflicting_item = _evidence("news", "duplicate", minute=2)
    with pytest.raises(EvidenceSelectionStateError, match="conflicting duplicate evidence"):
        _select(
            evidence=[item, conflicting_item],
            priorities=[priority],
            budget_tokens=1,
        )


def test_conflicting_duplicate_priority_hash_or_class_fails_closed() -> None:
    first = _priority(
        "news",
        "duplicate",
        priority_class=EvidencePriorityClass.ORDINARY_CURRENT,
        tokens=1,
        semantic_hash=_hash("first"),
    )
    conflicting = first.model_copy(update={"semantic_hash": _hash("second")})

    with pytest.raises(EvidenceSelectionStateError, match="conflicting duplicate evidence priority"):
        _select(
            evidence=[_evidence("news", "duplicate", minute=1)],
            priorities=[first, conflicting],
            budget_tokens=1,
        )

    conflicting_class = first.model_copy(
        update={"priority_class": EvidencePriorityClass.CONFIRMED_INVALIDATION}
    )
    with pytest.raises(EvidenceSelectionStateError, match="conflicting duplicate evidence priority"):
        _select(
            evidence=[_evidence("news", "duplicate", minute=1)],
            priorities=[first, conflicting_class],
            budget_tokens=1,
        )


def test_low_value_backlog_is_deferred_before_higher_priority_evidence() -> None:
    result = _select(
        evidence=[
            _evidence("news", "backlog", minute=3),
            _evidence("options", "regime", minute=1),
            _evidence("market", "key-level", minute=2),
        ],
        priorities=[
            _priority(
                "news",
                "backlog",
                priority_class=EvidencePriorityClass.BACKLOG,
                tokens=1,
            ),
            _priority(
                "options",
                "regime",
                priority_class=EvidencePriorityClass.MARKET_OPTIONS_REGIME,
                tokens=1,
            ),
            _priority(
                "market",
                "key-level",
                priority_class=EvidencePriorityClass.CONFIRMED_KEY_LEVEL,
                tokens=1,
            ),
        ],
        budget_tokens=2,
    )

    assert result.retained_evidence_ids == ("key-level", "regime")
    assert [item.evidence_id for item in result.deferred_queue] == ["backlog"]
    retained = {
        item.evidence_id: item for item in result.decisions if item.outcome == "retained"
    }
    assert retained["key-level"].reasons == ("priority:confirmed_key_level",)
    assert retained["regime"].reasons == ("priority:market_options_regime",)
