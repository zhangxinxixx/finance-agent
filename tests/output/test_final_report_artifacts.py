from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.analysis.agents import AgentBias, AgentOutput, AgentStatus
from apps.analysis.strategy.card import build_strategy_card
from apps.analysis.strategy.schemas import StrategyCardOutput
from apps.output.final_report import (
    _render_strategy_card_markdown,
    _safe_artifact_dir,
    write_final_report,
    write_strategy_card,
)
from apps.renderer.markdown.final_report import render_final_report_markdown

_CREATED_AT = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)
_TRADE_DATE = "2026-05-14"

# ═══════════════════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════════════════


def _snapshot(*, unavailable_modules: list[str] | None = None) -> dict:
    return {
        "snapshot_id": "XAUUSD:2026-05-14:analysis",
        "run_id": "run-final-test",
        "input_snapshot_ids": {
            "analysis_snapshot": "XAUUSD:2026-05-14:analysis",
            "macro": "macro:2026-05-14",
            "options": "cme-options:2026-05-14",
        },
        "metadata": {
            "symbol": "XAUUSD",
            "as_of": _TRADE_DATE,
            "unavailable_modules": unavailable_modules or [],
        },
        "source_refs": [{"source": "analysis_snapshot", "snapshot_id": "XAUUSD:2026-05-14:analysis"}],
    }


def _agent_output(*, module: str, bias: AgentBias, confidence: float, status: AgentStatus = AgentStatus.SUCCESS, **kw) -> AgentOutput:
    defaults: dict = {
        "version": "1.0",
        "module": module,
        "agent_name": f"{module}_agent",
        "snapshot_id": "XAUUSD:2026-05-14:analysis",
        "input_snapshot_ids": {module: f"{module}:2026-05-14"},
        "bias": bias,
        "confidence": confidence,
        "key_findings": kw.pop("key_findings", [f"{module} finding"]),
        "risk_points": kw.pop("risk_points", [f"{module} risk"]),
        "watchlist": kw.pop("watchlist", [f"{module} watch"]),
        "invalid_conditions": kw.pop("invalid_conditions", []),
        "summary": kw.pop("summary", f"{module} summary"),
        "source_refs": kw.pop("source_refs", [{"source": module, "ref": f"{module}:2026-05-14"}]),
        "status": status,
        "created_at": _CREATED_AT,
    }
    defaults.update(kw)
    return AgentOutput(**defaults)


def _render_final_report_md(*, snapshot: dict | None = None) -> str:
    snap = snapshot or _snapshot()
    return render_final_report_markdown(
        snapshot=snap,
        macro_output=_agent_output(module="macro", bias=AgentBias.BULLISH, confidence=0.72),
        options_output=_agent_output(module="options", bias=AgentBias.BULLISH, confidence=0.70),
        risk_output=_agent_output(module="risk", bias=AgentBias.BULLISH, confidence=0.62),
        coordinator_output=_agent_output(
            module="coordinator",
            bias=AgentBias.BULLISH,
            confidence=0.61,
            key_findings=["Macro and options aligned.", "Options prior finding: Call wall near 2450"],
            summary="Bullish research view with constrained confidence.",
        ),
        created_at=_CREATED_AT,
    )


def _strategy_card(*, run_id: str = "run-card-test", coordinator_bias: AgentBias = AgentBias.BULLISH) -> StrategyCardOutput:
    return build_strategy_card(
        snapshot={**_snapshot(), "run_id": run_id},
        coordinator_output=_agent_output(
            module="coordinator",
            bias=coordinator_bias,
            confidence=0.61,
            key_findings=["Options prior finding: Call wall near 2450", "Options prior finding: Put support near 2350"],
            summary="Bullish research view.",
            risk_points=["Technical data unavailable."],
            invalid_conditions=["Invalidate if snapshot lineage changes."],
            watchlist=["DGS10", "CME option walls"],
            input_snapshot_ids={
                "analysis_snapshot": "XAUUSD:2026-05-14:analysis",
                "coordinator": "XAUUSD:2026-05-14:analysis",
                "macro": "macro:2026-05-14",
                "options": "cme-options:2026-05-14",
                "risk": "risk:2026-05-14",
            },
        ),
        risk_output=_agent_output(module="risk", bias=AgentBias.BULLISH, confidence=0.68),
        created_at=_CREATED_AT,
    )


# ═══════════════════════════════════════════════════════════════════════
# _safe_artifact_dir tests
# ═══════════════════════════════════════════════════════════════════════


def test_safe_artifact_dir_builds_expected_path(tmp_path: Path) -> None:
    path = _safe_artifact_dir(
        tmp_path,
        artifact_type="final_report",
        asset="XAUUSD",
        trade_date=_TRADE_DATE,
        run_id="run-a",
    )
    expected = (tmp_path / "outputs" / "final_report" / "XAUUSD" / _TRADE_DATE / "run-a").resolve()
    assert path == expected
    assert path.is_relative_to((tmp_path).resolve())


@pytest.mark.parametrize(
    ("component", "kwargs"),
    [
        ("artifact_type", {"artifact_type": ".."}),
        ("asset", {"asset": "../escape"}),
        ("trade_date", {"trade_date": "../../bad"}),
        ("run_id", {"run_id": ".."}),
        ("artifact_type", {"artifact_type": ""}),
        ("asset", {"asset": "foo/bar"}),
    ],
)
def test_safe_artifact_dir_rejects_path_traversal(
    tmp_path: Path, component: str, kwargs: dict
) -> None:
    params: dict = {
        "artifact_type": "strategy_card",
        "asset": "XAUUSD",
        "trade_date": _TRADE_DATE,
        "run_id": "run-a",
    }
    params.update(kwargs)
    with pytest.raises(ValueError, match=component):
        _safe_artifact_dir(tmp_path, **params)


# ═══════════════════════════════════════════════════════════════════════
# write_final_report tests
# ═══════════════════════════════════════════════════════════════════════


def test_write_final_report_creates_file_with_correct_content(tmp_path: Path) -> None:
    markdown = _render_final_report_md()
    result = write_final_report(
        storage_root=tmp_path,
        markdown=markdown,
        asset="XAUUSD",
        trade_date=_TRADE_DATE,
        run_id="run-final-01",
    )

    assert result["artifact_type"] == "final_report"
    assert result["skipped"] is False
    assert len(result["paths"]) == 1

    written_path = Path(result["paths"][0])
    assert written_path.exists()
    content = written_path.read_text(encoding="utf-8")
    assert "# XAUUSD 盘前综合报告" in content
    assert "snapshot_id: XAUUSD:2026-05-14:analysis" in content
    assert "## 数据口径" in content
    assert "## 免责声明" in content


def test_write_final_report_creates_parent_dirs(tmp_path: Path) -> None:
    """Parent directories that don't exist should be created automatically."""
    deep_root = tmp_path / "nested" / "project"
    markdown = _render_final_report_md()

    result = write_final_report(
        storage_root=deep_root,
        markdown=markdown,
        trade_date=_TRADE_DATE,
        run_id="run-dir-test",
    )

    written_path = Path(result["paths"][0])
    assert written_path.exists()
    assert written_path.is_file()


def test_write_final_report_default_no_overwrite(tmp_path: Path) -> None:
    """Default overwrite=False should raise FileExistsError on second write."""
    markdown = _render_final_report_md()
    run_id = "run-overwrite-test"

    # first write — ok
    write_final_report(
        storage_root=tmp_path,
        markdown=markdown,
        trade_date=_TRADE_DATE,
        run_id=run_id,
    )

    # second write — should fail
    with pytest.raises(FileExistsError, match="already exists"):
        write_final_report(
            storage_root=tmp_path,
            markdown=markdown,
            trade_date=_TRADE_DATE,
            run_id=run_id,
        )


def test_write_final_report_overwrite_true_replaces_file(tmp_path: Path) -> None:
    markdown_v1 = _render_final_report_md()
    run_id = "run-overwrite-ok"

    # first write
    result1 = write_final_report(
        storage_root=tmp_path,
        markdown=markdown_v1,
        trade_date=_TRADE_DATE,
        run_id=run_id,
    )
    path1 = Path(result1["paths"][0])

    # modify the markdown
    markdown_v2 = markdown_v1 + "\n<!-- version 2 -->\n"
    result2 = write_final_report(
        storage_root=tmp_path,
        markdown=markdown_v2,
        trade_date=_TRADE_DATE,
        run_id=run_id,
        overwrite=True,
    )

    path2 = Path(result2["paths"][0])
    assert path1 == path2
    assert "version 2" in path2.read_text(encoding="utf-8")


def test_write_final_report_rejects_path_traversal(tmp_path: Path) -> None:
    markdown = _render_final_report_md()

    with pytest.raises(ValueError):
        write_final_report(
            storage_root=tmp_path,
            markdown=markdown,
            trade_date=_TRADE_DATE,
            run_id="../../escape",
        )


def test_write_final_report_normalizes_run_id(tmp_path: Path) -> None:
    """Verify that run_id is normalized through normalize_run_id."""
    markdown = _render_final_report_md()

    # auto-generated run_id
    result = write_final_report(
        storage_root=tmp_path,
        markdown=markdown,
        trade_date=_TRADE_DATE,
        run_id=None,  # type: ignore[arg-type]
    )
    path = Path(result["paths"][0])
    assert path.exists()
    # run_id should be a timestamp pattern
    run_dir = path.parent
    assert run_dir.name  # non-empty
    assert "T" in run_dir.name or "Z" in run_dir.name


def test_write_final_report_returns_summary_dict_with_paths(tmp_path: Path) -> None:
    markdown = _render_final_report_md()
    result = write_final_report(
        storage_root=tmp_path,
        markdown=markdown,
        trade_date=_TRADE_DATE,
        run_id="run-summary",
    )

    assert isinstance(result, dict)
    assert "artifact_type" in result
    assert "paths" in result
    assert "skipped" in result
    assert result["artifact_type"] == "final_report"
    assert isinstance(result["paths"], list)
    assert all(isinstance(p, str) for p in result["paths"])


# ═══════════════════════════════════════════════════════════════════════
# _render_strategy_card_markdown tests
# ═══════════════════════════════════════════════════════════════════════


def test_render_strategy_card_markdown_contains_key_sections() -> None:
    card = _strategy_card()
    md = _render_strategy_card_markdown(card)

    assert "# XAUUSD Strategy Card" in md
    assert "## Research View" in md
    assert "## Risk Points" in md
    assert "## Invalid Conditions" in md
    assert "## Watchlist" in md
    assert "## Data Provenance" in md
    assert "## Disclaimer" in md
    assert "is_trade_instruction: False" in md
    assert "Research output only" in md


def test_render_strategy_card_markdown_contains_card_fields() -> None:
    card = _strategy_card()
    md = _render_strategy_card_markdown(card)

    assert card.asset in md
    assert card.trade_date in md
    assert card.run_id in md
    assert card.scenario_summary in md
    for rp in card.risk_points:
        assert rp in md


def test_render_strategy_card_markdown_no_execution_language() -> None:
    """Strategy card markdown must not contain executable trading language."""
    card = _strategy_card()
    md = _render_strategy_card_markdown(card).lower()

    for forbidden in ("buy", "sell", "enter", "stop loss", "take profit"):
        assert forbidden not in md, f"forbidden word '{forbidden}' found"


# ═══════════════════════════════════════════════════════════════════════
# write_strategy_card tests
# ═══════════════════════════════════════════════════════════════════════


def test_write_strategy_card_creates_json_and_md(tmp_path: Path) -> None:
    card = _strategy_card(run_id="run-card-01")
    result = write_strategy_card(
        storage_root=tmp_path,
        card=card,
    )

    assert result["artifact_type"] == "strategy_card"
    assert result["skipped"] is False
    assert len(result["paths"]) == 2

    paths = [Path(p) for p in result["paths"]]
    json_path = next(p for p in paths if p.suffix == ".json")
    md_path = next(p for p in paths if p.suffix == ".md")

    assert json_path.exists()
    assert md_path.exists()


def test_write_strategy_card_json_uses_model_dump_mode_json(tmp_path: Path) -> None:
    """JSON output must be produced via model_dump(mode='json') for correct types."""
    card = _strategy_card(run_id="run-serial")
    result = write_strategy_card(storage_root=tmp_path, card=card)

    json_path = Path(result["paths"][0])
    data = json.loads(json_path.read_text(encoding="utf-8"))

    # Enum values serialized as strings (mode='json')
    assert data["bias"] == "bullish"
    # datetime serialized as ISO string
    assert isinstance(data["created_at"], str)
    # Literal[False] preserved
    assert data["is_trade_instruction"] is False


def test_write_strategy_card_md_is_valid_markdown(tmp_path: Path) -> None:
    card = _strategy_card(run_id="run-md")
    result = write_strategy_card(storage_root=tmp_path, card=card)

    md_path = next(Path(p) for p in result["paths"] if Path(p).suffix == ".md")
    content = md_path.read_text(encoding="utf-8")

    assert "# XAUUSD Strategy Card" in content
    assert "## Research View" in content
    assert "## Disclaimer" in content
    # key levels extracted
    assert "Call wall near 2450" in content
    assert "Put support near 2350" in content


def test_write_strategy_card_default_no_overwrite(tmp_path: Path) -> None:
    card = _strategy_card(run_id="run-card-no-overwrite")

    # first write
    write_strategy_card(storage_root=tmp_path, card=card)

    # second write — should fail
    with pytest.raises(FileExistsError, match="already exist"):
        write_strategy_card(storage_root=tmp_path, card=card)


def test_write_strategy_card_overwrite_true_replaces_both_files(tmp_path: Path) -> None:
    card = _strategy_card(run_id="run-card-overwrite")

    # first write
    r1 = write_strategy_card(storage_root=tmp_path, card=card)

    # update card with different summary
    card2 = build_strategy_card(
        snapshot={**_snapshot(), "run_id": "run-card-overwrite"},
        coordinator_output=_agent_output(
            module="coordinator",
            bias=AgentBias.BEARISH,
            confidence=0.45,
            key_findings=["Options prior finding: Call wall near 2500"],
            summary="Bearish research view.",
            risk_points=["New risk."],
            input_snapshot_ids={
                "analysis_snapshot": "XAUUSD:2026-05-14:analysis",
                "coordinator": "XAUUSD:2026-05-14:analysis",
            },
        ),
        created_at=_CREATED_AT,
    )

    r2 = write_strategy_card(storage_root=tmp_path, card=card2, overwrite=True)

    # same paths
    assert r1["paths"] == r2["paths"]

    md_path = next(Path(p) for p in r2["paths"] if Path(p).suffix == ".md")
    content = md_path.read_text(encoding="utf-8")
    assert "bearish" in content.lower()  # scenario_summary includes bias text
    assert "New risk" in content


def test_write_strategy_card_creates_parent_dirs(tmp_path: Path) -> None:
    deep_root = tmp_path / "deep" / "nested" / "root"
    card = _strategy_card(run_id="run-deep")

    result = write_strategy_card(storage_root=deep_root, card=card)

    for p in result["paths"]:
        assert Path(p).exists()


def test_write_strategy_card_rejects_path_traversal(tmp_path: Path) -> None:
    card = _strategy_card(run_id="../../../etc")

    with pytest.raises(ValueError):
        write_strategy_card(storage_root=tmp_path, card=card)


def test_write_strategy_card_does_not_call_llm_or_network(tmp_path: Path) -> None:
    """The writer must be a pure filesystem operation."""
    card = _strategy_card(run_id="run-pure")
    result = write_strategy_card(storage_root=tmp_path, card=card)

    assert len(result["paths"]) == 2
    for p in result["paths"]:
        assert Path(p).exists()
        assert Path(p).stat().st_size > 0


def test_write_strategy_card_changed_trade_date_goes_to_different_dir(tmp_path: Path) -> None:
    card1 = _strategy_card(run_id="run-diff-date")
    card2 = build_strategy_card(
        snapshot={**_snapshot(), "run_id": "run-diff-date", "metadata": {"symbol": "XAUUSD", "as_of": "2026-05-15"}},
        coordinator_output=_agent_output(
            module="coordinator",
            bias=AgentBias.BULLISH,
            confidence=0.5,
            key_findings=[],
            summary="Day 2.",
            input_snapshot_ids={
                "analysis_snapshot": "XAUUSD:2026-05-15:analysis",
                "coordinator": "XAUUSD:2026-05-15:analysis",
            },
        ),
        created_at=_CREATED_AT,
    )

    r1 = write_strategy_card(storage_root=tmp_path, card=card1)
    r2 = write_strategy_card(storage_root=tmp_path, card=card2)

    dates1 = {p.split("/")[-3] for p in r1["paths"]}
    dates2 = {p.split("/")[-3] for p in r2["paths"]}

    assert dates1 == {"2026-05-14"}
    assert dates2 == {"2026-05-15"}
