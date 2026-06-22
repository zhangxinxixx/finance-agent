from __future__ import annotations

from apps.api.schemas.common import WarningItem


def merge_warning_items(*warning_groups: list[WarningItem]) -> list[WarningItem]:
    merged: list[WarningItem] = []
    seen: set[tuple[str, str | None, str]] = set()
    for group in warning_groups:
        for warning in group:
            key = (warning.code, warning.field, warning.message)
            if key in seen:
                continue
            seen.add(key)
            merged.append(warning)
    return merged


def build_artifact_lineage_warnings(
    *,
    artifact_id: str,
    run_id: str | None,
    run_snapshot_id: str | None,
    artifact_snapshot_id: str | None,
    artifact_input_snapshot_ids: dict | None = None,
) -> list[WarningItem]:
    warnings: list[WarningItem] = []

    def _append_warning(code: str, message: str, *, field: str | None = None, hint: str | None = None) -> None:
        warnings.append(WarningItem(code=code, message=message, field=field, hint=hint))

    if artifact_snapshot_id and run_snapshot_id and artifact_snapshot_id != run_snapshot_id:
        _append_warning(
            "artifact-lineage-snapshot-mismatch",
            f"Artifact {artifact_id} metadata snapshot_id={artifact_snapshot_id} but run snapshot is {run_snapshot_id}",
            field="snapshot_id",
            hint="RunArtifact metadata 与 TaskRun.snapshot_id 不一致，需回查 registry 历史行或重建 artifact lineage。",
        )

    for key in ("analysis_snapshot", "coordinator"):
        value = artifact_input_snapshot_ids.get(key) if isinstance(artifact_input_snapshot_ids, dict) else None
        if isinstance(value, str) and value and run_snapshot_id and value != run_snapshot_id:
            _append_warning(
                f"artifact-lineage-{key}-mismatch",
                f"Artifact {artifact_id} input_snapshot_ids[{key}]={value} but run snapshot is {run_snapshot_id}",
                field="snapshot_id",
                hint="Artifact registry 中的显式快照绑定与当前 run 不一致，需回查历史写入或重建 registry 行。",
            )

    if not warnings and artifact_snapshot_id and run_id and not run_snapshot_id:
        _append_warning(
            "artifact-lineage-run-snapshot-missing",
            f"Artifact {artifact_id} keeps metadata snapshot_id={artifact_snapshot_id} but run {run_id} has no snapshot_id",
            field="snapshot_id",
            hint="TaskRun.snapshot_id 缺失，当前只能依赖 artifact metadata 回退恢复 lineage。",
        )

    return warnings


def build_report_lineage_warnings(
    *,
    report_id: str,
    report_run_id: str | None,
    report_snapshot_id: str | None,
    resolved_run_id: str | None,
    resolved_snapshot_id: str | None,
    final_run_id: str | None = None,
    final_snapshot_id: str | None = None,
) -> list[WarningItem]:
    warnings: list[WarningItem] = []

    def _append_warning(code: str, message: str, *, field: str | None = None, hint: str | None = None) -> None:
        warnings.append(WarningItem(code=code, message=message, field=field, hint=hint))

    if report_snapshot_id and resolved_snapshot_id and report_snapshot_id != resolved_snapshot_id:
        _append_warning(
            "report-lineage-snapshot-mismatch",
            f"Report {report_id} declares snapshot_id={report_snapshot_id} but resolved snapshot is {resolved_snapshot_id}",
            field="snapshot_id",
            hint="报告登记的 snapshot_id 与实际解析到的分析快照不一致，需回查 report_items 或补齐标准化绑定。",
        )

    if report_run_id and resolved_run_id and report_run_id != resolved_run_id:
        _append_warning(
            "report-lineage-run-mismatch",
            f"Report {report_id} declares run_id={report_run_id} but resolved snapshot run is {resolved_run_id}",
            field="run_id",
            hint="报告登记的 run_id 与实际解析到的分析快照 run_id 不一致，需回查标准报告绑定。",
        )

    if resolved_snapshot_id and final_snapshot_id and resolved_snapshot_id != final_snapshot_id:
        _append_warning(
            "report-lineage-final-snapshot-mismatch",
            f"Resolved snapshot {resolved_snapshot_id} does not match final_result snapshot {final_snapshot_id}",
            field="snapshot_id",
            hint="最终结果与分析快照绑定不一致，需检查 FinalAnalysisResult / report_items 的 lineage 写入。",
        )

    if resolved_run_id and final_run_id and resolved_run_id != final_run_id:
        _append_warning(
            "report-lineage-final-run-mismatch",
            f"Resolved snapshot run {resolved_run_id} does not match final_result run {final_run_id}",
            field="run_id",
            hint="最终结果与分析快照 run_id 不一致，需检查 FinalAnalysisResult / report_items 的 lineage 写入。",
        )

    if report_snapshot_id and final_snapshot_id and report_snapshot_id != final_snapshot_id:
        _append_warning(
            "report-lineage-declared-final-snapshot-mismatch",
            f"Report {report_id} declares snapshot_id={report_snapshot_id} but final_result snapshot is {final_snapshot_id}",
            field="snapshot_id",
        )

    if report_run_id and final_run_id and report_run_id != final_run_id:
        _append_warning(
            "report-lineage-declared-final-run-mismatch",
            f"Report {report_id} declares run_id={report_run_id} but final_result run is {final_run_id}",
            field="run_id",
        )

    return warnings
