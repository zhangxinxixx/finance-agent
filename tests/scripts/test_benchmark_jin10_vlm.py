from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from apps.analysis.jin10.vlm_benchmark import (
    balanced_gate_decision,
    bbox_iou,
    build_daily_weekly_manifest,
    run_benchmark,
    score_downstream_result,
    score_page_result,
    summarize_model_runs,
)
from scripts.benchmark_jin10_vlm import _run_once, resolve_sample_assets


def test_daily_weekly_manifest_contains_fixed_cover_and_chart_samples() -> None:
    manifest = build_daily_weekly_manifest(storage_root="storage")

    assert [sample["sample_id"] for sample in manifest["samples"]] == [
        "daily-224307-cover",
        "daily-224307-chart",
        "weekly-224284-cover",
        "weekly-224284-chart",
    ]
    assert {sample["report_type"] for sample in manifest["samples"]} == {"daily", "weekly"}
    assert [sample["kind"] for sample in manifest["samples"]] == ["cover", "chart", "cover", "chart"]


def test_bbox_iou_uses_exact_overlap() -> None:
    assert bbox_iou([0, 0, 100, 100], [0, 0, 100, 100]) == 1.0
    assert bbox_iou([0, 0, 100, 100], [50, 50, 150, 150]) == 0.1429
    assert bbox_iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0


def test_balanced_gate_requires_absolute_thresholds_and_no_baseline_regression() -> None:
    baseline_rows = [
        {
            "success": True,
            "json_valid": True,
            "classification_score": 1.0,
            "topic_score": 1.0,
            "key_number_score": 0.96,
            "bbox_iou": 0.86,
            "order_correct": True,
            "semantic_key": "stable",
            "latency_ms": 1000,
        }
        for _ in range(20)
    ]
    candidate_rows = [dict(item, latency_ms=1100) for item in baseline_rows]

    baseline = summarize_model_runs("baseline", baseline_rows)
    candidate = summarize_model_runs("gpt-5.6-luna", candidate_rows)
    decision = balanced_gate_decision(baseline=baseline, candidate=candidate)

    assert decision["passed"] is True
    assert decision["failures"] == []

    regressed = dict(candidate)
    regressed["key_number_rate"] = 0.95
    failed = balanced_gate_decision(baseline=baseline, candidate=regressed)

    assert failed["passed"] is False
    assert "key_number_rate_below_baseline" in failed["failures"]


def test_semantic_stability_is_computed_within_each_sample() -> None:
    rows = [
        {"sample_id": "a", "success": True, "json_valid": True, "order_correct": True, "semantic_key": "a"},
        {"sample_id": "a", "success": True, "json_valid": True, "order_correct": True, "semantic_key": "a"},
        {"sample_id": "b", "success": True, "json_valid": True, "order_correct": True, "semantic_key": "b"},
        {"sample_id": "b", "success": True, "json_valid": True, "order_correct": True, "semantic_key": "b"},
    ]

    summary = summarize_model_runs("gpt-5.6-luna", rows)

    assert summary["semantic_stability"] == 1.0


def test_page_and_downstream_scoring_require_expected_evidence_and_trace() -> None:
    sample = {
        "figure_id": "fig_p2_002",
        "page_no": 2,
        "expected": {
            "classification": "黄金投资者周报",
            "topic_tokens": ["Put", "Call"],
            "key_numbers": ["4065"],
            "bbox": [100, 200, 500, 600],
        },
    }
    page = score_page_result(
        sample,
        {
            "status": "success",
            "markdown": "黄金投资者周报 Put Call 4065",
            "charts": [{"bbox": [100, 200, 500, 600]}],
        },
        latency_ms=100,
    )
    downstream = score_downstream_result(
        sample,
        '{"figure_id":"fig_p2_002","page_no":2,"key_numbers":["4065"],"trend":"震荡"}',
        latency_ms=120,
    )

    assert page["classification_score"] == 1.0
    assert page["topic_score"] == 1.0
    assert page["key_number_score"] == 1.0
    assert page["bbox_iou"] == 1.0
    assert downstream["json_valid"] is True
    assert downstream["order_correct"] is True
    assert downstream["key_number_score"] == 1.0
    assert downstream["semantic_key"]


def test_page_semantic_key_ignores_non_evidence_wording_drift() -> None:
    sample = {
        "expected": {
            "classification": "黄金投资者周报",
            "topic_tokens": ["Put", "Call"],
            "key_numbers": ["4065"],
            "bbox": None,
        }
    }

    first = score_page_result(
        sample,
        {"status": "success", "markdown": "黄金投资者周报 Put Call 4065。", "charts": []},
        latency_ms=10,
    )
    second = score_page_result(
        sample,
        {"status": "success", "markdown": "黄金投资者周报：额外说明。Put/Call，4065", "charts": []},
        latency_ms=12,
    )

    assert first["semantic_key"] == second["semantic_key"]


def test_benchmark_runner_writes_partitioned_evidence_and_requires_both_stages(tmp_path) -> None:
    manifest = {
        "schema_version": 1,
        "repeats": 1,
        "samples": [
            {
                "sample_id": "daily-cover",
                "figure_id": None,
                "page_no": 1,
                "expected": {
                    "classification": "每日金银报告",
                    "topic_tokens": ["黄金"],
                    "key_numbers": [],
                    "bbox": None,
                },
            }
        ],
    }

    def page_runner(model, sample):
        return {
            "payload": {"status": "success", "markdown": "每日金银报告 黄金", "charts": []},
            "latency_ms": 10,
            "attempts": 1,
            "usage": {},
        }

    result = run_benchmark(
        manifest=manifest,
        output_dir=tmp_path / "run-001",
        page_runner=page_runner,
        max_workers=2,
    )

    assert result["overall_passed"] is True
    assert len(result["runs"]) == 1
    assert result["metrics"]["candidate"]["model"] == "gpt-5.6-luna"
    assert (tmp_path / "run-001" / "manifest.json").is_file()
    assert (tmp_path / "run-001" / "metrics.json").is_file()
    assert (tmp_path / "run-001" / "decision.json").is_file()
    assert (tmp_path / "run-001" / "comparison.md").is_file()
    assert (tmp_path / "run-001" / "runs.partial.json").is_file()


def test_resolve_sample_assets_uses_full_page_for_page_stage_and_crop_for_downstream(tmp_path) -> None:
    parsed = tmp_path / "parsed"
    figures = parsed / "figures"
    figures.mkdir(parents=True)
    page = tmp_path / "page-2.png"
    crop = figures / "fig_p2_002.png"
    page.write_bytes(b"page")
    crop.write_bytes(b"crop")
    (parsed / "page_images.json").write_text(
        '{"pages":[{"page_no":2,"image_path":"' + str(page) + '"}]}',
        encoding="utf-8",
    )
    sample = {"parsed_dir": str(parsed), "page_no": 2, "figure_id": "fig_p2_002"}

    assets = resolve_sample_assets(sample)

    assert assets["page_image"] == page
    assert assets["analysis_image"] == crop


def test_benchmark_cli_validate_only_runs_from_repo_root() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    completed = subprocess.run(
        [sys.executable, "scripts/benchmark_jin10_vlm.py", "--validate-only", "--repeats", "1"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert '"daily-224307-cover"' in completed.stdout


def test_benchmark_cli_records_explicit_reasoning_effort() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/benchmark_jin10_vlm.py",
            "--validate-only",
            "--repeats",
            "1",
            "--reasoning-effort",
            "high",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert '"reasoning_effort": "high"' in completed.stdout


def test_benchmark_cli_records_explicit_model() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/benchmark_jin10_vlm.py",
            "--validate-only",
            "--repeats",
            "1",
            "--model",
            "gpt-5.5",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert '"model": "gpt-5.5"' in completed.stdout


def test_benchmark_does_not_stack_retry_after_timeout() -> None:
    calls = 0

    def fail():
        nonlocal calls
        calls += 1
        raise TimeoutError("upstream still running")

    result = _run_once(fail, result_key="payload")

    assert calls == 1
    assert result["attempts"] == 1
