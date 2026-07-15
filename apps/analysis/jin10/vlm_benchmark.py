"""Deterministic scoring helpers for the Jin10 daily/weekly VLM benchmark."""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable


DEFAULT_MODEL_SPEC = {"role": "candidate", "provider": "cockpit", "model": "gpt-5.6-luna"}


def build_daily_weekly_manifest(*, storage_root: str | Path = "storage") -> dict[str, Any]:
    root = Path(storage_root)
    return {
        "schema_version": 1,
        "repeats": 5,
        "samples": [
            _sample(
                root,
                sample_id="daily-224307-cover",
                report_type="daily",
                date="2026-07-13",
                run_id="224307",
                kind="cover",
                page_no=1,
                classification="每日金银报告",
                topic_tokens=["黄金", "CPI"],
                key_numbers=["4100"],
            ),
            _sample(
                root,
                sample_id="daily-224307-chart",
                report_type="daily",
                date="2026-07-13",
                run_id="224307",
                kind="chart",
                page_no=12,
                figure_id="fig_p12_001",
                bbox=[241, 2307, 1559, 3015],
                topic_tokens=["黄金", "CPI"],
                key_numbers=["4100"],
            ),
            _sample(
                root,
                sample_id="weekly-224284-cover",
                report_type="weekly",
                date="2026-07-11",
                run_id="224284",
                kind="cover",
                page_no=1,
                classification="黄金投资者周报",
                topic_tokens=["黄金", "区间震荡"],
                key_numbers=["4065", "4235"],
            ),
            _sample(
                root,
                sample_id="weekly-224284-chart",
                report_type="weekly",
                date="2026-07-11",
                run_id="224284",
                kind="chart",
                page_no=2,
                figure_id="fig_p2_002",
                bbox=[301, 2370, 1859, 3276],
                topic_tokens=["Put", "Call"],
                key_numbers=[],
            ),
        ],
    }


def _sample(
    root: Path,
    *,
    sample_id: str,
    report_type: str,
    date: str,
    run_id: str,
    kind: str,
    page_no: int,
    classification: str | None = None,
    topic_tokens: list[str] | None = None,
    key_numbers: list[str] | None = None,
    figure_id: str | None = None,
    bbox: list[int] | None = None,
) -> dict[str, Any]:
    return {
        "sample_id": sample_id,
        "report_type": report_type,
        "date": date,
        "run_id": run_id,
        "kind": kind,
        "page_no": page_no,
        "figure_id": figure_id,
        "parsed_dir": str(root / "parsed" / "jin10" / date / run_id),
        "expected": {
            "classification": classification,
            "topic_tokens": topic_tokens or [],
            "key_numbers": key_numbers or [],
            "bbox": bbox,
        },
    }


def bbox_iou(left: list[int] | None, right: list[int] | None) -> float | None:
    if not left or not right or len(left) != 4 or len(right) != 4:
        return None
    lx1, ly1, lx2, ly2 = (float(value) for value in left)
    rx1, ry1, rx2, ry2 = (float(value) for value in right)
    ix1, iy1 = max(lx1, rx1), max(ly1, ry1)
    ix2, iy2 = min(lx2, rx2), min(ly2, ry2)
    intersection = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    left_area = max(0.0, lx2 - lx1) * max(0.0, ly2 - ly1)
    right_area = max(0.0, rx2 - rx1) * max(0.0, ry2 - ry1)
    union = left_area + right_area - intersection
    return round(intersection / union, 4) if union else 0.0


def score_page_result(
    sample: dict[str, Any],
    payload: dict[str, Any],
    *,
    latency_ms: int,
) -> dict[str, Any]:
    expected = sample.get("expected") or {}
    text = " ".join(
        [
            str(payload.get("markdown") or ""),
            *[str(item.get("text") or "") for item in payload.get("blocks") or [] if isinstance(item, dict)],
            *[str(item.get("title") or "") for item in payload.get("charts") or [] if isinstance(item, dict)],
        ]
    )
    expected_bbox = expected.get("bbox")
    bbox_scores = [
        bbox_iou(expected_bbox, item.get("bbox"))
        for item in payload.get("charts") or []
        if isinstance(item, dict) and item.get("bbox")
    ]
    classification_score = _token_score(text, [expected.get("classification")]) if expected.get("classification") else None
    topic_score = _token_score(text, expected.get("topic_tokens") or [])
    key_number_score = _token_score(text, expected.get("key_numbers") or [])
    best_bbox = max((value for value in bbox_scores if value is not None), default=None)
    return {
        "success": payload.get("status") == "success",
        "json_valid": isinstance(payload, dict),
        "classification_score": classification_score,
        "topic_score": topic_score,
        "key_number_score": key_number_score,
        "bbox_iou": best_bbox,
        "order_correct": True,
        "semantic_key": json.dumps(
            {
                "classification": classification_score,
                "topic": topic_score,
                "key_numbers": key_number_score,
                "bbox_pass": best_bbox is None or best_bbox >= 0.85,
            },
            sort_keys=True,
        ),
        "latency_ms": latency_ms,
    }


def score_downstream_result(
    sample: dict[str, Any],
    content: str,
    *,
    latency_ms: int,
) -> dict[str, Any]:
    parsed = _parse_json_object(content)
    expected = sample.get("expected") or {}
    serialized = json.dumps(parsed, ensure_ascii=False, sort_keys=True) if parsed is not None else content
    expected_figure = sample.get("figure_id")
    expected_page = sample.get("page_no")
    order_correct = parsed is not None and (
        (not expected_figure or str(parsed.get("figure_id") or "") == str(expected_figure))
        and (expected_page is None or int(parsed.get("page_no") or 0) == int(expected_page))
    )
    semantic = {}
    if parsed is not None:
        semantic = {key: parsed.get(key) for key in ("classification", "topic", "key_numbers", "trend", "direction")}
    return {
        "success": parsed is not None and bool(content.strip()),
        "json_valid": parsed is not None,
        "classification_score": (
            _token_score(serialized, [expected.get("classification")]) if expected.get("classification") else None
        ),
        "topic_score": _token_score(serialized, expected.get("topic_tokens") or []),
        "key_number_score": _token_score(serialized, expected.get("key_numbers") or []),
        "bbox_iou": None,
        "order_correct": order_correct,
        "semantic_key": json.dumps(semantic, ensure_ascii=False, sort_keys=True),
        "latency_ms": latency_ms,
    }


def summarize_model_runs(model: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    return {
        "model": model,
        "runs": total,
        "success_rate": _mean_bool(rows, "success"),
        "json_valid_rate": _mean_bool(rows, "json_valid"),
        "classification_rate": _mean_score(rows, "classification_score"),
        "topic_rate": _mean_score(rows, "topic_score"),
        "key_number_rate": _mean_score(rows, "key_number_score"),
        "bbox_median_iou": _median_score(rows, "bbox_iou"),
        "order_rate": _mean_bool(rows, "order_correct"),
        "semantic_stability": _semantic_stability(rows),
        "latency_p95_ms": _percentile([float(row.get("latency_ms") or 0) for row in rows], 0.95),
    }


def balanced_gate_decision(*, baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    thresholds = {
        "success_rate": 0.98,
        "json_valid_rate": 0.99,
        "classification_rate": 0.99,
        "topic_rate": 0.99,
        "key_number_rate": 0.95,
        "bbox_median_iou": 0.85,
        "order_rate": 0.99,
        "semantic_stability": 0.90,
    }
    failures: list[str] = []
    for key, threshold in thresholds.items():
        if float(candidate.get(key) or 0) < threshold:
            failures.append(f"{key}_below_threshold")
        if float(candidate.get(key) or 0) < float(baseline.get(key) or 0):
            failures.append(f"{key}_below_baseline")
    baseline_latency = float(baseline.get("latency_p95_ms") or 0)
    candidate_latency = float(candidate.get("latency_p95_ms") or 0)
    if baseline_latency > 0 and candidate_latency > baseline_latency * 1.25:
        failures.append("latency_p95_above_1_25x_baseline")
    return {
        "passed": not failures,
        "failures": failures,
        "thresholds": thresholds,
        "baseline_model": baseline.get("model"),
        "candidate_model": candidate.get("model"),
    }


def absolute_gate_decision(metrics: dict[str, Any]) -> dict[str, Any]:
    thresholds = {
        "success_rate": 0.98,
        "json_valid_rate": 0.99,
        "classification_rate": 0.99,
        "topic_rate": 0.99,
        "key_number_rate": 0.95,
        "bbox_median_iou": 0.85,
        "order_rate": 0.99,
        "semantic_stability": 0.90,
    }
    failures = [
        f"{key}_below_threshold"
        for key, threshold in thresholds.items()
        if float(metrics.get(key) or 0) < threshold
    ]
    return {"passed": not failures, "failures": failures, "thresholds": thresholds}


def run_benchmark(
    *,
    manifest: dict[str, Any],
    output_dir: str | Path,
    page_runner: Callable[[dict[str, str], dict[str, Any]], dict[str, Any]],
    max_workers: int = 1,
    progress_callback: Callable[[int, int, dict[str, Any]], None] | None = None,
    model_spec: dict[str, str] | None = None,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    repeats = max(1, int(manifest.get("repeats") or 1))
    rows: list[dict[str, Any]] = []
    total_jobs = len(manifest.get("samples") or []) * repeats
    resolved_model = dict(model_spec or DEFAULT_MODEL_SPEC)
    _write_json(output / "manifest.json", manifest)

    jobs = [
        (sample, repeat)
        for sample in manifest.get("samples") or []
        for repeat in range(1, repeats + 1)
    ]
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        futures = {
            executor.submit(_run_one, "page", resolved_model, sample, repeat, page_runner): (sample, repeat)
            for sample, repeat in jobs
        }
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            _write_json(output / "runs.partial.json", _sorted_rows(rows, manifest))
            if progress_callback is not None:
                progress_callback(len(rows), total_jobs, row)

    rows = _sorted_rows(rows, manifest)
    candidate_metrics = summarize_model_runs(str(resolved_model["model"]), rows)
    metrics = {"candidate": candidate_metrics}
    gate = absolute_gate_decision(candidate_metrics)

    decision = {
        "overall_passed": gate["passed"],
        "production_switch_allowed": False,
        "production_switch_reason": "daily_weekly_benchmark_only",
        "gate": gate,
    }
    _write_json(output / "runs.json", rows)
    _write_json(output / "metrics.json", metrics)
    _write_json(output / "decision.json", decision)
    (output / "comparison.md").write_text(_render_comparison(metrics, decision), encoding="utf-8")
    return {**decision, "runs": rows, "metrics": metrics}


def _run_one(
    stage: str,
    model: dict[str, str],
    sample: dict[str, Any],
    repeat: int,
    runner: Callable[[dict[str, str], dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    raw = runner(model, sample)
    if stage == "page":
        score = score_page_result(sample, raw.get("payload") or {}, latency_ms=int(raw.get("latency_ms") or 0))
    else:
        score = score_downstream_result(
            sample,
            str(raw.get("content") or ""),
            latency_ms=int(raw.get("latency_ms") or 0),
        )
    return {
        "stage": stage,
        "role": model["role"],
        "provider": model["provider"],
        "model": model["model"],
        "sample_id": sample.get("sample_id"),
        "repeat": repeat,
        "attempts": int(raw.get("attempts") or 1),
        "usage": raw.get("usage") or {},
        "error": raw.get("error"),
        "raw_result": raw.get("payload") if stage == "page" else raw.get("content"),
        **score,
    }


def _sorted_rows(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    sample_order = {item["sample_id"]: index for index, item in enumerate(manifest.get("samples") or [])}
    stage_order = {"page": 0, "downstream": 1}
    role_order = {"baseline": 0, "candidate": 1}
    return sorted(
        rows,
        key=lambda item: (
            stage_order.get(str(item.get("stage")), 99),
            role_order.get(str(item.get("role")), 99),
            sample_order.get(str(item.get("sample_id")), 99),
            int(item.get("repeat") or 0),
        ),
    )


def _mean_bool(rows: list[dict[str, Any]], key: str) -> float:
    return round(sum(bool(row.get(key)) for row in rows) / len(rows), 4) if rows else 0.0


def _semantic_stability(rows: list[dict[str, Any]]) -> float:
    grouped: dict[str, list[str]] = {}
    for row in rows:
        semantic_key = str(row.get("semantic_key") or "")
        if semantic_key:
            grouped.setdefault(str(row.get("sample_id") or "unknown"), []).append(semantic_key)
    if not grouped:
        return 1.0
    scores = [Counter(values).most_common(1)[0][1] / len(values) for values in grouped.values()]
    return round(statistics.fmean(scores), 4)


def _mean_score(rows: list[dict[str, Any]], key: str) -> float:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return round(statistics.fmean(values), 4) if values else 1.0


def _median_score(rows: list[dict[str, Any]], key: str) -> float:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    return round(statistics.median(values), 4) if values else 1.0


def _percentile(values: list[float], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return int(ordered[index])


def _token_score(text: str, tokens: list[Any]) -> float:
    normalized = [str(token) for token in tokens if token not in {None, ""}]
    if not normalized:
        return 1.0
    return round(sum(token.lower() in text.lower() for token in normalized) / len(normalized), 4)


def _parse_json_object(content: str) -> dict[str, Any] | None:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines.pop()
        text = "\n".join(lines).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _render_comparison(metrics: dict[str, Any], decision: dict[str, Any]) -> str:
    lines = [
        "# Jin10 Daily/Weekly VLM Benchmark",
        "",
        "## Candidate",
        "",
        "```json",
        json.dumps(metrics["candidate"], ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    lines.extend(
        [
            "## Decision",
            "",
            f"- overall_passed: {str(decision['overall_passed']).lower()}",
            "- production_switch_allowed: false",
            "- scope: daily/weekly benchmark only",
            "",
        ]
    )
    return "\n".join(lines)
