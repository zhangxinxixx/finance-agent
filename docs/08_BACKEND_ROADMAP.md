# 后端改造规划

本规划基于当前代码，不表示所有条目已实现。已存在能力应收敛统一，缺失能力按 Phase 补齐。

## Phase 1：Schema / Contract 统一

目标：

- 统一 API schemas、DB models、frontend types 之间的字段命名和状态枚举。

涉及文件：

- `apps/api/schemas/common.py`
- `apps/api/schemas/source_trace.py`
- `apps/api/schemas/task_run.py`
- `apps/api/schemas/report.py`
- `apps/api/schemas/review.py`
- `apps/api/schemas/strategy.py`
- `apps/api/schemas/market.py`
- `apps/api/schemas/data_source.py`
- `apps/frontend-web/src/types/*`
- `apps/frontend-web/src/adapters/*`

新增/修改模型：

- 优先复用现有 `TraceableResponse`、`SourceRef`、`ArtifactRef`、`SnapshotRef`。

API：

- 不新增大 API，先做 response contract 对齐。

前端影响：

- 所有页面 adapters。

验收标准：

- 前后端 typecheck 通过。
- 文档能列出每个页面消费的 contract。

风险：

- 兼容旧 report / strategy API 时字段不一致。

## Phase 2：TaskRun / TaskStep 状态机

目标：

- 将 C4 agent、final report、strategy card、report index 写入显式 TaskStep。

涉及文件：

- `database/models/task.py`
- `apps/premarket.py`
- `apps/worker/runner.py`
- `apps/api/services/task_service.py`
- `apps/api/schemas/task_run.py`

字段：

- `run_id`
- `step_id`
- `status`
- `input_refs`
- `output_refs`
- `source_refs`
- `artifact_refs`
- `error_type`
- `retry_count`

API：

- `/api/runs/{run_id}`
- `/api/runs/{run_id}/steps`
- `/api/runs/{run_id}/artifacts`

前端影响：

- Agent Tasks
- Report Detail

验收标准：

- 单次 premarket run 每个关键输出都有 TaskStep。
- 失败/blocked/retryable 语义清晰。

风险：

- 旧任务历史数据字段缺失，需要 adapter 兼容。

## Phase 3：SourceTrace / Snapshot

目标：

- 让 report、strategy、agent output 都能反查完整 source trace。

涉及文件：

- `apps/api/services/source_trace_service.py`
- `apps/api/schemas/source_trace.py`
- `database/models/analysis.py`
- `database/models/report.py`

模型：

- `SourceRef`
- `ArtifactRef`
- `SnapshotRef`
- `AnalysisSnapshot`
- `ReportArtifact`

API：

- `/api/source-trace/{snapshot_id}`
- `/api/source-trace/by-report/{report_id}`
- `/api/source-trace/by-strategy/{strategy_card_id}`

前端影响：

- Report Detail
- Strategy Center
- Agent Tasks

验收标准：

- 任一 report_id 能返回 run/snapshot/source/artifact 链路。

风险：

- legacy artifacts 无 snapshot_id。

## Phase 4：报告三产物模型

目标：

- 每个 report family 都标准化登记 `source.md`、`analysis.md`、`visual.html`、`report_structured.json`。

涉及文件：

- `database/models/report.py`
- `apps/api/services/report_service.py`
- `apps/output/final_report.py`
- `apps/renderer/*`
- Jin10 / CME report writers

模型：

- `ReportItem`
- `ReportArtifact`

API：

- `/api/reports/{report_id}/artifacts`
- `/api/reports/{report_id}/source`
- `/api/reports/{report_id}/analysis`
- `/api/reports/{report_id}/visual`
- `/api/reports/{report_id}/analysis-inputs`

前端影响：

- Reports
- Report Detail

验收标准：

- 新生成报告必须有标准 artifact 清单。

风险：

- 历史报告需要 legacy adapter，不应强行改写历史产物。

## Phase 5：ReviewItem

目标：

- 把低置信、解析异常、Agent 冲突、报告待复核统一进入 ReviewItem。

涉及文件：

- `database/models/analysis.py`
- `apps/api/services/review_service.py`
- parsers / VLM / Agent pipeline

API：

- `/api/reviews`
- review action APIs

前端影响：

- Review Center
- Agent Tasks
- Report Detail

验收标准：

- 每个 review item 有 source_refs/evidence_refs/impact_report_ids。

风险：

- 自动创建 ReviewItem 需要避免重复和噪声。

## Phase 6：DataSourceStatus

目标：

- 统一 `LIVE / STALE / PARTIAL / FALLBACK / OFFLINE / MOCK / MANUAL_REQUIRED`。

涉及文件：

- `database/models/analysis.py`
- `database/queries/data_source_status.py`
- `apps/api/services/source_service.py`
- collectors / pipelines

API：

- `/api/data-sources/status`
- `/api/data-status/summary`

前端影响：

- Data Ingestion
- Dashboard
- Market Monitor

验收标准：

- 数据状态可追踪到 latest raw/parsed/snapshot/run。

风险：

- 当前 status 字段已有历史值，需要枚举迁移策略。

## Phase 7：StrategyCard API

目标：

- 收敛 `/api/strategy-card*` legacy 和 `/api/strategy-cards*` read model。

涉及文件：

- `apps/api/services/report_service.py`
- `apps/analysis/strategy/card.py`
- `apps/frontend-web/src/adapters/strategy.ts`

API：

- `/api/strategy-cards`
- `/api/strategy-cards/latest`
- `/api/strategy-cards/{strategy_card_id}`

前端影响：

- Strategy Center
- Dashboard

验收标准：

- 策略卡显示 source trace，不包含自动交易下单语义。

风险：

- 旧 dashboard 仍消费 `/api/strategy-card/latest`。

## Phase 8：Market K线 API

目标：

- 让 Market Monitor 图表统一读取 `MarketCandle`。

涉及文件：

- `database/models/analysis.py` 的 `MarketCandle`
- `apps/api/services/market_service.py`
- collectors / backfill scripts

API：

- 当前 `/api/market/monitor/history`
- 后续可明确 `/api/market/candles`

前端影响：

- Market Monitor
- Dashboard sparklines

验收标准：

- 图表能标明 asset/timeframe/source/ref。

风险：

- 多数据源时间粒度和 timezone 对齐。

## Phase 9：Knowledge / Settings API

目标：

- 把知识库、Playbook、Settings、Agent governance 稳定成配置中心。

涉及文件：

- `apps/api/services/knowledge_service.py`
- `apps/api/services/settings_service.py`
- `apps/api/services/playbook_service.py`
- `apps/analysis/agents/registry.py`
- `database/models/analysis.py`
- `database/models/playbook.py`

API：

- `/api/knowledge/items*`
- `/api/playbooks*`
- `/api/settings*`
- `/api/agents/*`

前端影响：

- Knowledge Base
- Settings

验收标准：

- 所有写操作有 audit_id/request_id。
- secret 不明文回显。

风险：

- 配置写入不能影响历史报告。
