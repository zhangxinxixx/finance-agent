# Trace Schema

> Contract 基线：2026-07-21。API 事实源为 `apps/api/schemas/common.py` 与 `source_trace.py`；持久化事实源为 `database/models/*`。

## 分类

`apps.analysis.agents.schemas.DataCategory` 定义：

| 值 | 含义 |
| --- | --- |
| `confirmed_data` | 可验证的结构化事实或原始数据 |
| `external_opinion` | 第三方或 LLM 的观点/文本判断 |
| `system_inference` | 系统基于输入作出的确定性推导 |

分类不能替代具体来源。任何重要结论仍需绑定可定位的 source 或 artifact。

## 公共对象

### SourceRef

当前公共 API 字段：

```json
{
  "source_id": "fred:DGS10:2026-07-21",
  "source_name": "FRED DGS10",
  "source_type": "api",
  "data_date": "2026-07-21",
  "endpoint": "series/DGS10",
  "captured_at": "2026-07-21T00:30:00Z",
  "file_path": "raw/macro/2026-07-21/dgs10.json",
  "sha256": "...",
  "url": "https://fred.stlouisfed.org/series/DGS10",
  "status": "confirmed_data"
}
```

`source_id`、`source_name`、`source_type` 必填；其他字段在公共 schema 中可选。领域 payload 可以保存 `used_for`、`warnings`、`provider_role` 等扩展信息，但不能假定所有 API SourceRef 都有这些字段。

### ArtifactRef

```json
{
  "artifact_id": "artifact-123",
  "artifact_type": "feature_json",
  "file_path": "features/news/2026-07-21/run-id/daily_market_brief.json",
  "storage_backend": "local_fs",
  "version": "1",
  "generated_at": "2026-07-21T00:35:00Z",
  "sha256": "..."
}
```

支持类型：`source_md`、`analysis_md`、`visual_html`、`structured_json`、`raw_file`、`parsed_file`、`feature_json`、`chart_snapshot`。

### SnapshotRef

包含 `snapshot_id`、`snapshot_type`、`data_date`、`run_id`、`data_status`、`created_at` 和 `input_snapshot_ids`。

### TraceableResponse

所有可追溯 read model 的共同字段：

```json
{
  "run_id": "...",
  "snapshot_id": "...",
  "data_status": "live",
  "source_refs": [],
  "artifact_refs": [],
  "warnings": []
}
```

`DataStatus` 当前为 `live`、`partial`、`stale`、`fallback`、`mock`、`unavailable`、`manual_required`。

## 持久化位置

| 表 | trace 字段 |
| --- | --- |
| `analysis_snapshots` | `input_snapshot_ids`、`source_refs`、artifact path |
| `agent_outputs` | `input_snapshot_ids`、`source_refs`、payload/hash |
| `final_analysis_results` | `input_snapshot_ids`、`source_refs` |
| `task_steps` | input/output/source/artifact refs（历史兼容 Text JSON） |
| `run_artifacts` | run/task identity、path、hash、typed source refs |
| `report_items` / `report_artifacts` | report identity、source refs、artifact metadata |
| `review_items` | 被复核结论的 source refs |
| `playbook_templates` | 模板来源 refs |

## 继承规则

1. Collector 创建 source identity，并归档 raw。
2. Parser/feature 追加自身 artifact，不覆盖上游 refs。
3. Analysis snapshot 汇总所有输入 snapshot/source refs。
4. Agent output 只引用实际消费的输入。
5. Fact Review 引用 claim evidence 和原 Agent output。
6. Report/strategy 绑定 Quality Gate 接受的 candidate；observe-only 产物保持独立身份。

## 校验

- ID 能解析到实际记录或文件。
- file path 使用仓库/存储相对路径，公开输出不泄露工作站绝对路径。
- `sha256` 与文件一致（声明时）。
- business date、captured/generated time 不混用。
- 外部意见不能标为 confirmed data。
- `source_refs=[]` 或历史缺口时返回 warning/partial/unavailable，不补造来源。

## 查询入口

- `/api/source-trace/{snapshot_id}`
- `/api/source-trace/by-report/{report_id}`
- `/api/source-trace/by-strategy/{strategy_card_id}`
- `/api/source-trace/by-artifact/{artifact_id}`
- `/api/runs/{run_id}/artifacts`
- `/api/artifacts/{artifact_id}`
