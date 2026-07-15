from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.analysis.figure_facts import FigureFact
from apps.output.figure_facts import (
    FigureFactConflictError,
    FigureFactLoadError,
    load_figure_fact,
    write_figure_fact,
)


def _fact(*, observation: str = "price holds above support") -> FigureFact:
    return FigureFact.build(
        figure_fact_id="figure-fact-v1",
        figure_id="fig_p10_002",
        report_id="225144",
        page_no=10,
        bbox=[80, 220, 900, 980],
        asset="XAUUSD",
        observations=[observation],
        numeric_values=[{"label": "support", "value": 4000, "unit": "USD"}],
        derived_claims=[],
        interpretation_limits=[],
        source_ref={
            "report_id": "225144",
            "figure_id": "fig_p10_002",
            "page_no": 10,
            "bbox": [80, 220, 900, 980],
        },
        quality_status="accepted",
        review_ref=None,
        image_content_hash="b" * 64,
        created_by_run_id="run-70",
    )


def test_writer_returns_storage_relative_registry_descriptor_and_loader_validates(
    tmp_path,
) -> None:
    storage_root = tmp_path / "storage"
    fact = _fact()

    result = write_figure_fact(
        storage_root=storage_root,
        trade_date="2026-07-22",
        fact=fact,
    )

    assert result.written is True
    assert not Path(result.storage_relative_path).is_absolute()
    assert result.storage_relative_path == (
        "outputs/figure_facts/XAUUSD/225144/2026-07-22/run-70/"
        "fig_p10_002/figure-fact-v1.json"
    )
    assert result.registry_artifact["artifact_type"] == "figure_fact_json"
    assert result.registry_artifact["metadata"]["confirmed_evidence"] is True
    assert load_figure_fact(
        storage_root=storage_root,
        storage_relative_path=result.storage_relative_path,
    ) == fact


def test_writer_is_idempotent_for_same_content_hash(tmp_path) -> None:
    first = write_figure_fact(
        storage_root=tmp_path,
        trade_date="2026-07-22",
        fact=_fact(),
    )
    second = write_figure_fact(
        storage_root=tmp_path,
        trade_date="2026-07-22",
        fact=_fact(),
    )

    assert first.written is True
    assert second.written is False
    assert second.content_hash == first.content_hash
    assert second.file_sha256 == first.file_sha256


def test_writer_revalidates_mutated_model_before_writing(tmp_path) -> None:
    fact = _fact()
    fact.observations.append("mutation after build")

    with pytest.raises(ValidationError, match="content_hash"):
        write_figure_fact(
            storage_root=tmp_path,
            trade_date="2026-07-22",
            fact=fact,
        )

    assert not (tmp_path / "outputs").exists()


def test_writer_rejects_same_id_with_different_content_hash(tmp_path) -> None:
    write_figure_fact(
        storage_root=tmp_path,
        trade_date="2026-07-22",
        fact=_fact(),
    )

    with pytest.raises(FigureFactConflictError, match="different content_hash"):
        write_figure_fact(
            storage_root=tmp_path,
            trade_date="2026-07-22",
            fact=_fact(observation="different observation"),
        )


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/figure.json",
        "outputs/figure_facts/../../secret.json",
        "parsed/figure_facts/value.json",
    ],
)
def test_loader_rejects_non_storage_relative_or_unsafe_paths(tmp_path, path: str) -> None:
    with pytest.raises(FigureFactLoadError):
        load_figure_fact(storage_root=tmp_path, storage_relative_path=path)


def test_loader_rejects_tampered_content(tmp_path) -> None:
    result = write_figure_fact(
        storage_root=tmp_path,
        trade_date="2026-07-22",
        fact=_fact(),
    )
    path = tmp_path / result.storage_relative_path
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["observations"] = ["tampered"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FigureFactLoadError, match="schema/hash"):
        load_figure_fact(
            storage_root=tmp_path,
            storage_relative_path=result.storage_relative_path,
        )
