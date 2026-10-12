"""Schema contract baseline tests for backend P0 Phase 1."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.api.schemas.common import (
    ArtifactType,
    DataStatus,
    ReportLifecycleStatus,
    ReviewStatus,
    TaskStatus,
    WarningItem,
)
from apps.api.schemas.claim import Claim, ClaimReview, ClaimReviewVerdict, ClaimType
from apps.api.schemas.data_source import DataSourceStatus
from apps.api.schemas.market import MarketChartContext
from apps.api.schemas.report import ReportArtifact, ReportDetail
from apps.api.schemas.source_trace import ArtifactRef, SnapshotRef, SourceRef, SourceTraceResponse
from apps.api.schemas.task_run import TaskRunResponse, TaskStepResponse


def test_contract_enums_match_phase1_baseline() -> None:
    assert [item.value for item in DataStatus] == [
        "live",
        "partial",
        "stale",
        "fallback",
        "mock",
        "unavailable",
        "manual_required",
    ]
    assert [item.value for item in TaskStatus] == [
        "queued",
        "running",
        "success",
        "partial_success",
        "failed",
        "retrying",
        "skipped",
        "degraded",
        "needs_review",
        "cancelled",
    ]
    assert [item.value for item in ArtifactType] == [
        "source_md",
        "analysis_md",
        "visual_html",
        "structured_json",
        "raw_file",
        "parsed_file",
        "feature_json",
        "chart_snapshot",
    ]
    assert [item.value for item in ReviewStatus] == [
        "not_required",
        "pending",
        "approved",
        "rejected",
        "rerun",
    ]
    assert [item.value for item in ReportLifecycleStatus] == [
        "draft",
        "generated",
        "snapshot_bound",
        "needs_review",
        "published",
        "exported",
        "archived",
    ]
    assert [item.value for item in ClaimType] == [
        "market_view",
        "data_fact",
        "causal_inference",
        "strategy_condition",
        "risk_warning",
    ]
    assert [item.value for item in ClaimReviewVerdict] == [
        "supported",
        "partially_supported",
        "unsupported",
        "contradicted",
        "insufficient_evidence",
    ]


def test_claim_and_claim_review_are_json_serializable() -> None:
    claim = Claim(
        claim_id="claim-001",
        text="Gamma Zero 位于 3325",
        claim_type=ClaimType.strategy_condition,
        source_refs=[SourceRef(source_id="src-cme", source_name="CME", source_type="pdf")],
        evidence_refs=[
            ArtifactRef(
                artifact_id="art-cme-001",
                artifact_type=ArtifactType.structured_json,
                file_path="storage/outputs/cme/2026-05-26/options_analysis.json",
            )
        ],
        confidence=0.72,
    )
    review = ClaimReview(
        claim_id="claim-001",
        verdict=ClaimReviewVerdict.supported,
        reason="CME 快照与报告中的数值一致。",
        conflicting_refs=[],
        reviewer_agent_id="fact_review_agent",
    )

    claim_payload = claim.model_dump(mode="json")
    review_payload = review.model_dump(mode="json")

    assert claim_payload["claim_type"] == "strategy_condition"
    assert claim_payload["source_refs"][0]["source_id"] == "src-cme"
    assert claim_payload["evidence_refs"][0]["artifact_type"] == "structured_json"
    assert review_payload["verdict"] == "supported"
    assert review_payload["reviewer_agent_id"] == "fact_review_agent"


def test_source_trace_response_carries_common_trace_fields() -> None:
    response = SourceTraceResponse(
        run_id="run-001",
        snapshot_id="snap-001",
        data_status=DataStatus.partial,
        source_refs=[
            SourceRef(
                source_id="src-001",
                source_name="CME Daily Bulletin",
                source_type="pdf",
                data_date="2026-05-26",
                captured_at=datetime(2026, 5, 26, 8, 30, tzinfo=UTC),
                file_path="storage/raw/cme/2026-05-26/bulletin.pdf",
                url="https://example.test/bulletin.pdf",
                status="available",
            )
        ],
        artifact_refs=[
            ArtifactRef(
                artifact_id="art-001",
                artifact_type=ArtifactType.raw_file,
                file_path="storage/raw/cme/2026-05-26/bulletin.pdf",
                generated_at=datetime(2026, 5, 26, 8, 31, tzinfo=UTC),
            )
        ],
        warnings=[WarningItem(code="source-stale", message="latest bulletin is stale")],
        snapshot=SnapshotRef(
            snapshot_id="snap-001",
            snapshot_type="analysis",
            data_date="2026-05-26",
            run_id="run-001",
        ),
    )

    payload = response.model_dump(mode="json")

    assert payload["run_id"] == "run-001"
    assert payload["snapshot_id"] == "snap-001"
    assert payload["data_status"] == "partial"
    assert payload["source_refs"][0]["source_id"] == "src-001"
    assert payload["artifact_refs"][0]["artifact_type"] == "raw_file"
    assert payload["warnings"][0]["code"] == "source-stale"
    assert payload["snapshot"]["snapshot_id"] == "snap-001"


def test_task_run_and_step_response_are_json_serializable() -> None:
    step = TaskStepResponse(
        step_id="step-001",
        run_id="run-001",
        snapshot_id="snap-001",
        task_name="cme_parse",
        stage="parser",
        task_kind="pdf_parse",
        status=TaskStatus.running,
        progress=0.5,
        duration_ms=1200,
        input_refs=[
            ArtifactRef(
                artifact_id="art-in-001",
                artifact_type=ArtifactType.raw_file,
                file_path="storage/raw/cme/2026-05-26/bulletin.pdf",
            )
        ],
        output_refs=[
            ArtifactRef(
                artifact_id="art-out-001",
                artifact_type=ArtifactType.parsed_file,
                file_path="storage/parsed/cme/2026-05-26/parsed.json",
            )
        ],
        source_refs=[SourceRef(source_id="src-001", source_name="CME", source_type="pdf")],
        artifact_refs=[
            ArtifactRef(
                artifact_id="art-001",
                artifact_type=ArtifactType.parsed_file,
                file_path="storage/parsed/cme/2026-05-26/parsed.json",
            )
        ],
    )
    run = TaskRunResponse(
        run_id="run-001",
        snapshot_id="snap-001",
        task_id="task-001",
        task_type="premarket",
        status=TaskStatus.running,
        current_stage="parser",
        progress=0.5,
        runtime_summary={"run_mode": "premarket_full_run", "quality_gate_status": "passed"},
        steps=[step],
    )

    payload = run.model_dump(mode="json")

    assert payload["status"] == "running"
    assert payload["steps"][0]["status"] == "running"
    assert payload["steps"][0]["task_kind"] == "pdf_parse"
    assert payload["steps"][0]["duration_ms"] == 1200
    assert payload["runtime_summary"]["run_mode"] == "premarket_full_run"
    assert payload["runtime_summary"]["quality_gate_status"] == "passed"
    assert payload["steps"][0]["input_refs"][0]["artifact_type"] == "raw_file"
    assert payload["steps"][0]["output_refs"][0]["artifact_type"] == "parsed_file"
    assert payload["steps"][0]["artifact_refs"][0]["artifact_type"] == "parsed_file"


def test_report_detail_contains_four_standard_artifacts() -> None:
    detail = ReportDetail(
        run_id="run-001",
        snapshot_id="snap-001",
        report_id="report-001",
        family="premarket",
        title="Premarket report",
        lifecycle_status=ReportLifecycleStatus.generated,
        artifacts=[
            ReportArtifact(artifact_id="a1", artifact_type=ArtifactType.source_md, file_path="source.md"),
            ReportArtifact(artifact_id="a2", artifact_type=ArtifactType.analysis_md, file_path="analysis.md"),
            ReportArtifact(artifact_id="a3", artifact_type=ArtifactType.visual_html, file_path="visual.html"),
            ReportArtifact(artifact_id="a4", artifact_type=ArtifactType.structured_json, file_path="report_structured.json"),
        ],
    )

    payload = detail.model_dump(mode="json")
    artifact_types = {item["artifact_type"] for item in payload["artifacts"]}

    assert artifact_types == {"source_md", "analysis_md", "visual_html", "structured_json"}


def test_market_chart_context_keeps_data_status_and_source_refs() -> None:
    context = MarketChartContext(
        run_id="run-001",
        snapshot_id="snap-001",
        symbol="XAUUSD",
        timeframe="15m",
        quote={"last": 3360.5},
        candles=[{"time": "2026-05-26T09:00:00Z", "open": 3358.0, "high": 3361.0, "low": 3357.5, "close": 3360.5}],
        data_status=DataStatus.live,
        source_refs=[SourceRef(source_id="src-quote", source_name="OpenBB", source_type="api")],
    )

    payload = context.model_dump(mode="json")

    assert payload["data_status"] == "live"
    assert payload["source_refs"][0]["source_id"] == "src-quote"


def test_data_source_status_schema_exposes_phase1_baseline() -> None:
    status = DataSourceStatus(
        run_id="run-001",
        snapshot_id="snap-001",
        source_id="fred",
        source_name="FRED",
        priority=1,
        config_status="configured",
        runtime_status="ok",
        data_status=DataStatus.live,
        affected_modules=["macro", "dashboard"],
    )

    payload = status.model_dump(mode="json")

    assert payload["source_id"] == "fred"
    assert payload["data_status"] == "live"
    assert payload["affected_modules"] == ["macro", "dashboard"]
