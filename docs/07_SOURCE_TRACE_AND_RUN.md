# Run / Snapshot / SourceTrace

## 目标

把每个前端结论、报告、策略卡片和 Agent 输出追溯到：

- raw source
- parsed artifact
- feature snapshot
- analysis snapshot
- agent output
- report artifact
- strategy card

## Run

模型：

- `database/models/task.py` 的 `TaskRun`
- `database/models/task.py` 的 `TaskStep`

API：

- `GET /api/runs`
- `GET /api/runs/{run_id}`
- `GET /api/runs/{run_id}/steps`
- `GET /api/runs/{run_id}/logs`
- `GET /api/runs/{run_id}/artifacts`

前端：

- `/agent-tasks`
- `/agent-tasks/:runId`
- `apps/frontend-web/src/adapters/agentTasks.ts`

## Snapshot

模型：

- `database/models/analysis.py` 的 `AnalysisSnapshot`

文件：

- `apps/analysis/snapshots/builder.py`
- `apps/worker/runner.py` 的 `_persist_analysis_snapshot()`

关键字段：

- `snapshot_id`
- `asset`
- `trade_date`
- `run_id`
- `input_snapshot_ids`
- `source_refs`
- `macro`
- `options`
- `positioning`
- `news`
- `technical`
- `payload`
- `artifact_path`

## SourceTrace

API schema：

- `apps/api/schemas/source_trace.py`

Service：

- `apps/api/services/source_trace_service.py`

API：

- `GET /api/source-trace/{snapshot_id}`
- `GET /api/source-trace/by-report/{report_id}`
- `GET /api/source-trace/by-strategy/{strategy_card_id}`

前端消费：

- Reports / Report Detail
- Strategy Center
- Agent Tasks

## ArtifactRef / SourceRef / SnapshotRef

Pydantic schema：

- `SourceRef`
- `ArtifactRef`
- `SnapshotRef`
- `SourceTraceResponse`

用途：

- `SourceRef` 描述外部数据或 raw source。
- `ArtifactRef` 描述本地文件产物。
- `SnapshotRef` 描述 feature/analysis snapshot。

## 当前链路

```text
TaskRun
  -> TaskStep
    -> input_refs / output_refs / source_refs / artifact_refs
  -> AnalysisSnapshot
    -> AgentOutput
    -> FinalAnalysisResult
      -> ReportItem / ReportArtifact
      -> StrategyCard read model
```

当前不足：

- 并非所有 legacy report 都有完整 `ReportItem` / `ReportArtifact`。
- TaskStep 的 `artifact_refs` 与最终 ReportArtifact 之间还需要统一。
- C4 agent/final report/strategy card 在 worker 末尾执行，未完全拆成显式 TaskStep。

## 验收标准

后续任意重要 report / strategy / dashboard 指标，都应能回答：

- 这个结论来自哪个 `run_id`？
- 用了哪个 `snapshot_id`？
- 原始数据 `source_refs` 是什么？
- 中间和最终 `artifact_refs` 在哪里？
- 是否包含 mock / fallback / stale / manual_required？
