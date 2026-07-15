# Mermaid 图索引

> 图表基线：2026-07-21；代码变化后应与对应事实源一起更新。

| 图 | 事实源与用途 |
| --- | --- |
| `system-architecture.mmd` | API、Dagster、领域 pipeline、数据库与文件层总览 |
| `backend-pipeline.mmd` | `dagster_finance/graphs/premarket.py` 与 Quality Gate 主链 |
| `data-flow.mmd` | `raw -> parsed -> features -> analysis -> outputs` |
| `agent-flow.mmd` | domain agents、Coordinator、Fact Review、Quality Gate 与 fallback |
| `frontend-page-map.mmd` | `apps/frontend-web/src/main.tsx` 当前路由 |
| `report-artifacts-flow.mmd` | report/artifact 的来源、分析、结构化与可视化关系 |
| `source-trace-flow.mmd` | source、snapshot、agent、report 与 strategy lineage |
| `news-pipeline-flow.mmd` | 新闻采集、feature、brief、follow-up 和 read model |

图只表达代码结构，不证明某个外部源当日可用或某次定时 run 已成功。运行事实仍以 source status、Dagster run、TaskRun/TaskStep 和实际 artifact 为准。
