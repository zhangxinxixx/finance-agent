from __future__ import annotations

import copy
import hashlib

import pytest
from pydantic import ValidationError

from apps.analysis.figure_facts import (
    FigureFact,
    FigureFactQualityStatus,
    prepare_figure_replay,
    project_confirmed_evidence,
    select_figure_facts,
    select_parsed_figure,
)


def _fact(*, quality_status: str = "accepted", figure_fact_id: str | None = None) -> FigureFact:
    limits = [] if quality_status == "accepted" else ["awaiting visual review"]
    return FigureFact.build(
        figure_fact_id=figure_fact_id,
        figure_id="fig_p10_002",
        report_id="225144",
        page_no=10,
        bbox=[80, 220, 900, 980],
        asset="XAUUSD",
        observations=["价格在 4000 上方获得承接"],
        numeric_values=[{"label": "support", "value": 4000, "unit": "USD"}],
        derived_claims=[
            {
                "claim": "下方承接增强",
                "basis": ["价格回到 4000 上方"],
                "confidence": 0.72,
            }
        ],
        interpretation_limits=limits,
        source_ref={
            "report_id": "225144",
            "figure_id": "fig_p10_002",
            "page_no": 10,
            "bbox": [80, 220, 900, 980],
        },
        quality_status=quality_status,
        review_ref={"review_id": "review-1"} if limits else None,
        image_content_hash="a" * 64,
        created_by_run_id="run-70",
    )


def test_figure_fact_builds_versioned_contract_and_validates_hash() -> None:
    fact = _fact()

    assert fact.schema_version == "figure_fact.v1"
    assert fact.figure_fact_id.startswith("figure_fact_")
    assert len(fact.content_hash) == 64
    assert fact.quality_status is FigureFactQualityStatus.ACCEPTED

    tampered = fact.model_dump(mode="json")
    tampered["observations"] = ["tampered"]
    with pytest.raises(ValidationError, match="content_hash"):
        FigureFact.model_validate(tampered)


def test_figure_fact_is_frozen_and_nested_mutation_is_revalidated() -> None:
    fact = _fact()

    with pytest.raises(ValidationError, match="frozen_instance"):
        fact.asset = "SILVER"

    fact.observations.append("stale mutation")
    with pytest.raises(ValidationError, match="content_hash"):
        project_confirmed_evidence(fact)


def test_only_accepted_fact_projects_to_confirmed_evidence() -> None:
    accepted = _fact()
    needs_review = _fact(quality_status="needs_review")
    blocked = _fact(quality_status="blocked")

    confirmed = project_confirmed_evidence(accepted)
    assert confirmed is not None
    assert confirmed.quality_status == "accepted"
    assert project_confirmed_evidence(needs_review) is None
    assert project_confirmed_evidence(blocked) is None
    assert select_figure_facts(
        [blocked, accepted, needs_review], confirmed_only=True
    ) == [accepted]


def test_accepted_fact_requires_image_hash_and_direct_evidence() -> None:
    payload = _fact().model_dump(mode="json")
    payload.pop("figure_fact_id")
    payload.pop("content_hash")
    payload["image_content_hash"] = None
    with pytest.raises(ValidationError, match="image_content_hash"):
        FigureFact.build(**payload)

    payload["image_content_hash"] = "a" * 64
    payload["observations"] = []
    payload["numeric_values"] = []
    with pytest.raises(ValidationError, match="observations or numeric_values"):
        FigureFact.build(**payload)


def test_figure_fact_requires_source_bbox_to_match() -> None:
    payload = _fact().model_dump(mode="json")
    payload.pop("figure_fact_id")
    payload.pop("content_hash")
    payload["source_ref"]["bbox"] = [0, 0, 100, 100]

    with pytest.raises(ValidationError, match="source_ref.bbox"):
        FigureFact.build(**payload)

    payload["source_ref"]["bbox"] = 1
    with pytest.raises(ValidationError, match="source_ref.bbox"):
        FigureFact.build(**payload)


def test_prepare_single_figure_replay_is_read_only_and_hashes_image(tmp_path) -> None:
    figures_dir = tmp_path / "figures"
    figures_dir.mkdir()
    image_bytes = b"not-a-real-png-but-readable"
    (figures_dir / "fig_p10_002.png").write_bytes(image_bytes)
    figures = {
        "figures": [
            {
                "figure_id": "fig_p10_002",
                "page_no": 10,
                "bbox": [80, 220, 900, 980],
                "chart_image_path": "figures/fig_p10_002.png",
            },
            {
                "figure_id": "fig_p11_001",
                "page_no": 11,
                "bbox": [10, 20, 300, 400],
                "chart_image_path": "figures/fig_p11_001.png",
            },
        ]
    }
    original = copy.deepcopy(figures)

    replay = prepare_figure_replay(
        parsed_dir=tmp_path,
        figures_payload=figures,
        figure_id="fig_p10_002",
        report_id="225144",
        asset="XAUUSD",
    )

    assert replay.status == "ready"
    assert replay.figure_id == "fig_p10_002"
    assert replay.image_content_hash == hashlib.sha256(image_bytes).hexdigest()
    assert replay.source_ref["image_sha256"] == replay.image_content_hash
    assert figures == original


def test_prepare_single_figure_replay_marks_missing_or_unreadable_image_degraded(tmp_path) -> None:
    missing = {
        "figures": [
            {
                "figure_id": "fig_p2_001",
                "page_no": 2,
                "bbox": [0, 0, 100, 100],
                "chart_image_path": "figures/missing.png",
            }
        ]
    }
    replay = prepare_figure_replay(
        parsed_dir=tmp_path,
        figures_payload=missing,
        figure_id="fig_p2_001",
        report_id="225144",
        asset="XAUUSD",
    )
    assert replay.status == "degraded"
    assert replay.degraded_reasons == ["image_missing"]

    (tmp_path / "empty.png").write_bytes(b"")
    missing["figures"][0]["chart_image_path"] = "empty.png"
    replay = prepare_figure_replay(
        parsed_dir=tmp_path,
        figures_payload=missing,
        figure_id="fig_p2_001",
        report_id="225144",
        asset="XAUUSD",
    )
    assert replay.status == "degraded"
    assert replay.degraded_reasons == ["image_unreadable"]


def test_select_parsed_figure_requires_exactly_one_match() -> None:
    with pytest.raises(LookupError, match="not found"):
        select_parsed_figure([], figure_id="missing")
    duplicate = [
        {"figure_id": "fig_p2_001"},
        {"figure_id": "fig_p2_001"},
    ]
    with pytest.raises(ValueError, match="not unique"):
        select_parsed_figure(duplicate, figure_id="fig_p2_001")
