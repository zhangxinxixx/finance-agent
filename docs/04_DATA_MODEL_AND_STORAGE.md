# 数据模型与存储

> 代码基线：2026-07-21。

## 运行与可观测性

| 表 | 用途 |
| --- | --- |
| `task_runs` | canonical run；状态、进度、成本、snapshot、final result |
| `task_steps` | step 状态、输入输出、source/artifact refs、错误与重试 |
| `execution_events` | append-only 运行事件流 |
| `run_artifacts` | run / step 级标准 artifact registry |

数据库 `TaskStatus` 包括 `pending`、`running`、`success`、`failed`、`partial_success`、`degraded`、`blocked`、`cancelled`、`stale`。公共 API 还有自己的展示枚举，service 层负责兼容映射；两者不能直接假定一一同名。

## 分析与治理

`database/models/analysis.py` 当前定义：

- `analysis_snapshots`
- `agent_outputs`
- `llm_call_audits`
- `final_analysis_results`
- `data_source_status`
- `macro_observations`
- `feature_snapshots`
- `daily_source_health_snapshots` / `daily_source_health_items`
- `market_candles`
- `jin10_flash_messages` / `flash_cursor_state`
- `app_settings` / `app_secrets` / `app_setting_events`
- `prompt_versions` / `prompt_feedback`
- `review_items`

## 报告与领域表

- `report_items` / `report_artifacts`：标准报告索引与文件登记。
- `cme_raw_files` / `cme_option_rows` / `cme_parse_runs`：CME 原始文件、解析行与解析 run。
- `playbook_templates`：带版本、schema、来源引用的 playbook。

## JSON 兼容

分析和报告模型使用 `JSONB_COMPAT`：PostgreSQL 使用 JSONB，SQLite 测试使用 JSON。TaskStep 的若干历史兼容字段仍以 JSON 字符串保存在 Text 列中，读取时必须经过 service/schema 归一化。

## Migration 策略

- Alembic 配置位于 `database/migrations/`。
- 当前已有 revision `20260704_0001`，用于统一 runtime schema。
- FastAPI startup 调用 `run_database_migrations()`。
- `ensure_*_tables()` 与 additive DDL 仍存在，主要兼容旧数据库；新 schema 变化应优先通过可审计 migration 管理。

## 文件存储

```text
storage/
  raw/        外部原始响应、PDF、HTML、上传文件
  parsed/     结构化解析结果
  features/   可重复计算的快照和事件模型
  outputs/    报告、策略卡片、可视化和结构化输出
  logs/       运行日志
  evaluation/ shadow evaluation 产物
  strategy_history/ 策略历史与差异
```

推荐路径为 `<layer>/<domain>/<date>/<run_id>/...`。历史路径可能不含 `run_id`；兼容读取可以保留，但新 artifact 应登记 sha256、类型、生成时间、run/snapshot/source refs。
