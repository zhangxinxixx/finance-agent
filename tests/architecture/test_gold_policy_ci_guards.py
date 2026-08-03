from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = PROJECT_ROOT / ".github/workflows/ci.yml"

GOLD_POLICY_CI_TESTS = (
    "tests/analysis/test_gold_feature_snapshot_policy.py",
    "tests/analysis/test_gold_feature_snapshot_adapter.py",
    "tests/analysis/test_gold_real10y_v2_contract.py",
    "tests/analysis/test_gold_readiness_policy.py",
    "tests/analysis/test_gold_readiness_v2_contract.py",
    "tests/analysis/test_gold_feature_store.py",
    "tests/analysis/test_coordinator_agent.py",
    "tests/analysis/test_gold_analysis_policy.py",
    "tests/analysis/test_gold_analysis_v2_contract.py",
    "tests/analysis/test_gold_materiality_policy.py",
    "tests/analysis/test_gold_price_attribution_policy.py",
    "tests/analysis/test_gold_price_attribution_v2_contract.py",
    "tests/analysis/test_gold_state_v2_contract.py",
    "tests/analysis/test_gold_state_transition_v2_policy.py",
    "tests/analysis/test_gold_state_transition_policy.py",
    "tests/analysis/test_gold_strategy_v2_policy.py",
    "tests/analysis/test_gold_key_level_policy.py",
    "tests/analysis/test_gold_consistency_policy.py",
    "tests/analysis/test_gold_daily_close_runtime.py",
    "tests/analysis/test_gold_daily_close_delivery.py",
    "tests/analysis/test_gold_daily_close_batch.py",
    "tests/analysis/test_gold_daily_close_store.py",
    "tests/analysis/test_gold_daily_close_five_day_replay.py",
    "tests/analysis/test_gold_daily_close_v2_replay.py",
    "tests/analysis/test_gold_runtime_controls.py",
    "tests/scripts/test_run_daily_macro_close.py",
    "tests/scripts/test_run_gold_daily_close_chain.py",
    "tests/scripts/test_run_gold_daily_report.py",
    "tests/worker/test_artifact_registration.py",
    "tests/evaluation/replay",
    "tests/analysis/test_gold_policy_v1_baseline_manifest.py",
    "tests/architecture/test_gold_policy_ci_guards.py",
)

FORMAL_AUTHORITY_PATHS = (
    PROJECT_ROOT / "apps/analysis/gold_policy",
    PROJECT_ROOT / "apps/evaluation/replay",
    PROJECT_ROOT / "apps/features/market_data",
    PROJECT_ROOT / "apps/features/news/formal_events.py",
    PROJECT_ROOT / "apps/features/positioning/formal_snapshot.py",
    PROJECT_ROOT / "apps/renderer/gold_policy_report.py",
    PROJECT_ROOT / "apps/renderer/gold_policy_report_bundle.py",
    PROJECT_ROOT / "scripts/run_gold_daily_report.py",
)


def _gold_policy_job_body(workflow: str) -> str:
    match = re.search(
        r"^  gold-policy-core:\n(?P<body>(?:^(?:    |  $).*(?:\n|$))*)",
        workflow,
        re.MULTILINE,
    )
    assert match is not None, "CI workflow must define a gold-policy-core job"
    return match.group("body")


def _gold_policy_pytest_body(job: str) -> str:
    marker = "- name: Run Gold Policy core and replay safety tests"
    upload_marker = "- name: Upload Gold Policy JUnit results"
    assert marker in job and upload_marker in job
    return job.split(marker, maxsplit=1)[1].split(upload_marker, maxsplit=1)[0]


def _authority_python_paths() -> Iterable[Path]:
    for authority_path in FORMAL_AUTHORITY_PATHS:
        if authority_path.is_file():
            yield authority_path
        else:
            yield from sorted(authority_path.rglob("*.py"))


def _imported_modules(path: Path) -> Iterable[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from ((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.lineno, node.module


def _is_forbidden_authority_dependency(module: str) -> bool:
    parts = module.lower().split(".")
    return (
        any("jin10" in part or "reportory" in part for part in parts)
        or module == "apps.llm"
        or module.startswith("apps.llm.")
    )


def test_gold_policy_core_ci_contract_is_independent_and_replay_safe() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")
    job = _gold_policy_job_body(workflow)

    assert "name: Gold Policy core" in job
    assert "python-version: \"3.11\"" in job
    assert "uv sync --locked --extra dev" in job
    assert "no_proxy: 127.0.0.1,localhost,::1" in job
    assert "--junitxml=test-results/gold-policy-core.xml" in job
    assert "actions/upload-artifact@v4" in job
    assert "if: always()" in job
    assert "test-results/gold-policy-core.xml" in job

    pytest_body = _gold_policy_pytest_body(job)
    missing_tests = [path for path in GOLD_POLICY_CI_TESTS if path not in pytest_body]
    assert not missing_tests, (
        "gold-policy-core pytest must run the complete explicit Gold Policy and replay matrix; "
        f"missing: {', '.join(missing_tests)}"
    )


def test_formal_gold_policy_authority_does_not_import_jin10_or_llm_execution() -> None:
    violations: list[str] = []
    for path in _authority_python_paths():
        relative_path = path.relative_to(PROJECT_ROOT)
        for line_number, module in _imported_modules(path):
            if _is_forbidden_authority_dependency(module):
                violations.append(f"{relative_path}:{line_number}: {module}")

    assert not violations, (
        "formal Gold Policy authority must not import Jin10/Reportory or LLM gateway code; "
        "keep those dependencies proposal-only or outside the authority boundary:\n"
        + "\n".join(violations)
    )
