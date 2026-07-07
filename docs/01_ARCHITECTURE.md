# 总体架构

## 架构原则

- 后端负责采集、解析、特征计算、分析、报告生成和结构化 read model。
- 前端只消费 API 和展示状态，不计算策略结论。
- LLM / Agent 不替代确定性计算；确定性指标先由 collectors / parsers / features 生成。
- 每个结论尽量绑定 `run_id`、`snapshot_id`、`source_refs`、`artifact_refs`。
- 缺失数据必须显式暴露为 unavailable / fallback / mock / manual_required，不伪装成 live。

## 逻辑分层

```text
apps/frontend-web
  -> apps/api
    -> apps/scheduler
      -> apps/worker
        -> apps/collectors
        -> apps/parsers
        -> apps/features
        -> apps/analysis
        -> apps/renderer
        -> apps/output
    -> database
    -> storage
```

## 后端运行链路

API 层：

- `apps/api/main.py` 定义 FastAPI app、生命周期、路由。
- `apps/api/schemas/` 定义 API Pydantic contracts。
- `apps/api/services/` 承载业务 read model 和写请求处理。
- `apps/api/data_service.py` 是兼容层，转发到 services。

Scheduler：

- `apps/scheduler/runner.py` 使用后台线程触发 worker。
- `apps/api/main.py` lifespan 中使用 APScheduler 刷新 Jin10 quotes/kline/calendar/flash，并配置每日 premarket。

Worker：

- `apps/worker/runner.py` 是 premarket 主执行器。
- `apps/worker/pipelines/macro.py` 执行宏观链路。
- `apps/worker/pipelines/cme.py` 执行 CME 链路。

数据/分析：

- collectors 写 raw 或返回 collector results。
- parsers 把 raw 转成 structured rows / points。
- features 生成 macro snapshot、options snapshot 等 deterministic features。
- analysis 生成 analysis snapshot、agent outputs、final analysis result、strategy card。
- renderer/output 写 Markdown、HTML、JSON artifact。

## 前端运行链路

- `apps/frontend-web/src/main.tsx` 定义路由。
- `AppShell`、`AppSidebar`、`AppHeader` 构成中台框架。
- `adapters/apiClient.ts` 统一 fetch JSON。
- 页面 adapters 负责把后端 API 变成 view model。
- `src/mocks/` 仍存在，用于 fallback 或空状态演示；页面必须显式标注 mock/fallback。

## 数据库

模型入口：

- `database/models/task.py`
- `database/models/analysis.py`
- `database/models/report.py`
- `database/models/cme.py`
- `database/models/playbook.py`

当前迁移特点：

- `database/migrations/versions/` 当前没有实际 migration 文件。
- `apps/api/main.py` startup 调用 `ensure_task_tables()`、`ensure_analysis_tables()`、`ensure_report_tables()`。
- 这适合 MVP additive table/column，但长期需要 Alembic migration 策略。

## 存储

存储目录：

- `storage/raw`
- `storage/parsed`
- `storage/features`
- `storage/outputs`
- `storage/logs`

新 run artifact 逐步使用 `<layer>/<domain>/<date>/<run_id>/...`。历史产物仍存在非 run-partitioned 路径，例如 `storage/outputs/macro/<date>/macro_snapshot.md`。

## 已实现与待统一

已实现：

- FastAPI 只读和少量写操作 API。
- Run / TaskStep 基础状态机。
- SourceTrace API。
- ReportItem / ReportArtifact 标准表。
- Reports detail 前端。
- Agent registry / prompt governance / feedback。
- Settings / Review / DataSourceStatus。

待统一：

- domain agents/final report/strategy card 尚未完全拆成 TaskStep。
- 报告四类标准 artifact 需要按 report family 完整校准。
- Alembic migrations 缺失。
- 前端 mock/fallback 状态需要更严格展示。
