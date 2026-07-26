"""CI guards for the Analysis Memory production baseline."""

from __future__ import annotations

from pathlib import Path


def test_ci_runs_analysis_memory_focused_and_postgres_suites() -> None:
    workflow = (Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    focused_suites = {
        "tests/database/test_analysis_state_core.py",
        "tests/analysis/test_context_bundle.py",
        "tests/analysis/test_context_bundle_selection.py",
        "tests/analysis/test_evidence_delta_evaluator.py",
        "tests/analysis/test_state_materializer.py",
        "tests/analysis/test_figure_facts.py",
        "tests/output/test_context_bundle_artifacts.py",
        "tests/output/test_figure_fact_artifacts.py",
        "tests/worker/test_composite_state_shadow.py",
        "tests/worker/test_canary_materialization.py",
        "tests/worker/test_context_bundle_artifact_registration.py",
        "tests/analysis/test_state_bootstrap.py",
        "tests/scripts/test_bootstrap_analysis_state.py",
        "tests/api/test_analysis_memory_api.py",
    }
    for suite in focused_suites:
        assert suite in workflow

    assert "apps/analysis/evidence_delta" in workflow
    assert "apps/analysis/prompts/state_transition.py" in workflow
    assert "apps/worker/canary_materialization.py" in workflow
    assert "apps/worker/composite_analysis_pipeline.py" in workflow
    assert "apps/worker/runner.py" in workflow
    assert "analysis-memory-postgres:" in workflow
    assert "services:" in workflow
    assert "postgres:" in workflow
    assert "tests/database/test_analysis_memory_postgres.py" in workflow
    assert "ANALYSIS_MEMORY_POSTGRES_URL" in workflow
    assert "postgresql+psycopg2://" in workflow
    assert workflow.count("mkdir -p test-results &&") == 2
    assert "actions/upload-artifact@v4" in workflow


def test_canary_cas_has_no_intermediate_commit_before_terminal_outcome() -> None:
    runner = (Path(__file__).resolve().parents[2] / "apps/worker/runner.py").read_text(
        encoding="utf-8"
    )
    canary_block = runner.split(
        'raw_canary_request = canary_materialization_outputs.get(', 1
    )[1].split(
        'if bool(getattr(composite_outputs.get("agent_loop_decision")', 1
    )[0]
    assert "_persist_canary_terminal_result(" in canary_block
    assert "db.commit()" not in canary_block
    assert "with db.begin_nested():" in canary_block
