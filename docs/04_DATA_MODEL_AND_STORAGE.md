# 数据模型与存储

## 数据库模型分层

当前模型文件：

- `database/models/task.py`
- `database/models/analysis.py`
- `database/models/report.py`
- `database/models/cme.py`
- `database/models/playbook.py`

## TaskRun / TaskStep

文件：`database/models/task.py`

表：

- `task_runs`
- `task_steps`

关键字段：

- `TaskRun.id`
- `TaskRun.name`
- `TaskRun.task_type`
- `TaskRun.status`
- `TaskRun.current_stage`
- `TaskRun.progress`
- `TaskRun.snapshot_id`
- `TaskRun.final_result_id`
- `TaskRun.trade_date`
- `TaskStep.task_run_id`
- `TaskStep.name`
- `TaskStep.status`
- `TaskStep.input_refs`
- `TaskStep.output_refs`
- `TaskStep.artifact_refs`
- `TaskStep.source_refs`
- `TaskStep.input_json`
- `TaskStep.output_json`
- `TaskStep.error_json`
- `TaskStep.input_hash`
- `TaskStep.output_ref`
- `TaskStep.error_type`
- `TaskStep.retry_count`

状态：

- Task：`pending`、`running`、`success`、`failed`、`partial_success`、`degraded`、`blocked`、`cancelled`、`stale`
- Step：`pending`、`running`、`success`、`failed`、`skipped`、`blocked`

## Analysis

文件：`database/models/analysis.py`

表：

- `analysis_snapshots`
- `agent_outputs`
- `final_analysis_results`
- `data_source_status`
- `market_candles`
- `app_settings`
- `app_secrets`
- `app_setting_events`
- `prompt_versions`
- `review_items`
- `prompt_feedback`

用途：

- 保存统一 analysis snapshot。
- 保存 Agent 输出和最终分析结果。
- 保存数据源状态、市场 K 线、配置、密钥、审计事件、Prompt 版本、人工复核和反馈。

## Report

文件：`database/models/report.py`

表：

- `report_items`
- `report_artifacts`

关键字段：

- `report_id`
- `family`
- `report_type`
- `title`
- `asset`
- `trade_date`
- `run_id`
- `snapshot_id`
- `data_status`
- `lifecycle_status`
- `source_refs`
- `artifact_type`
- `file_path`
- `is_primary`
- `sha256`

用途：

- 为 Report Detail 提供统一报告索引和 artifact 入口。
- 支持 source / analysis / visual / evidence / structured 等 artifact 类型。

## CME

文件：`database/models/cme.py`

表：

- `cme_raw_files`
- `cme_option_rows`
- `cme_parse_runs`

用途：

- 归档 CME Daily Bulletin PDF。
- 保存期权解析行。
- 记录 parse run。

## Playbook

文件：`database/models/playbook.py`

表：

- `playbook_templates`

用途：

- 保存 playbook 模板版本、条件、动作、失效条件和 source refs。

## Migrations

当前状态：

- `database/migrations/versions/` 仅有 `__init__.py`。
- API startup 调用 `ensure_task_tables()`、`ensure_analysis_tables()`、`ensure_report_tables()`。
- 这些 helper 会 `create_all()` 并追加缺失列。

风险：

- 长期数据库演进不能只依赖 runtime additive DDL。
- 后续 schema 稳定后应补 Alembic migrations。

## Storage

当前目录：

```text
storage/
  raw/
  parsed/
  features/
  outputs/
  logs/
```

实际样例：

- `storage/raw/jin10/<date>/index.json`
- `storage/parsed/jin10/<date>/index.json`
- `storage/features/macro/<date>/macro_snapshot.json`
- `storage/outputs/macro/<date>/macro_snapshot.md`
- `storage/outputs/cme_options/<date>/options_analysis.json`
- `storage/outputs/cme_options/<date>/options_analysis.md`
- `storage/outputs/jin10/<date>/analysis.json`
- `storage/outputs/jin10/calendar_cache.json`
- `storage/outputs/jin10/quotes_cache.json`

Run-partitioned artifact helper：

- `apps/output/artifacts.py`

推荐规范：

```text
storage/<layer>/<domain>/<trade_date>/<run_id>/<artifact>
```

其中 `<layer>` 是 `raw`、`parsed`、`features`、`outputs` 中之一。
