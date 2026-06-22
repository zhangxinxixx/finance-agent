# 报告系统

## 目标

报告系统负责把 raw / parsed / features / analysis / agent outputs 转成可阅读、可追溯、可复核的报告产物。

当前报告系统同时存在：

- 标准 report tables / report detail API
- legacy final report / strategy card API
- CME options visual report
- Jin10 report bundle

## 关键代码

- `database/models/report.py`
- `apps/api/schemas/report.py`
- `apps/api/services/report_service.py`
- `apps/output/final_report.py`
- `apps/renderer/markdown/final_report.py`
- `apps/renderer/html/options_visual.py`
- `apps/analysis/jin10/*`
- `apps/analysis/options/*`

## 标准模型

表：

- `report_items`
- `report_artifacts`

主要 API：

- `GET /api/reports/index`
- `GET /api/reports/dates`
- `GET /api/reports/{report_id}`
- `GET /api/reports/{report_id}/artifacts`
- `GET /api/reports/{report_id}/source`
- `GET /api/reports/{report_id}/analysis`
- `GET /api/reports/{report_id}/visual`
- `GET /api/reports/{report_id}/evidence`
- `GET /api/reports/{report_id}/analysis-inputs`

## 三产物 / 四文件约定

文档和后续开发统一按以下 artifact 理解：

```text
source.md
analysis.md
visual.html
report_structured.json
```

实际代码状态：

- `source.md`：标准 API 有 `/source` 入口；各报告族是否都有 source artifact 需验证。
- `analysis.md`：final report、options、Jin10 已有 Markdown/analysis 类产物；标准 artifact 覆盖需验证。
- `visual.html`：CME visual report 和 Jin10 bundle 支持 HTML 视图；标准 `/visual` API 已存在。
- `report_structured.json`：final report renderer 构建 structured report；写入路径需按具体 run 验证。

## 当前报告族

| 报告族 | 当前入口 | 说明 |
| --- | --- | --- |
| Final Report | `/api/final-report/latest`、`/api/final-report`、`/api/reports/{report_id}` | C4 pipeline 输出 |
| Strategy Card | `/api/strategy-card/latest`、`/api/strategy-card`、`/api/strategy-cards*` | 策略卡 read model |
| CME Options | `/api/options/report`、`/api/options/visual-report*`、`/api/reports/{report_id}` | Markdown + HTML visual |
| Macro | `/api/macro/report`、`storage/outputs/macro/*` | 宏观快照 Markdown |
| Macro Event Follow-up | 待新增 `/api/reports/{report_id}` 标准入口 | 非交易日宏观/新闻事件影响补充报告，不替代正式综合报告 |
| Jin10 Daily / Weekly | `/api/jin10/daily-report*`、`/api/jin10/weekly-report*`、`/api/jin10/report-bundle*` | 报告 bundle + assets |
| Market Odds | `/api/market-odds/report` | 结构化摘要 |

## 非交易日补充报告口径

`macro_event_followup` 是后续新增的正式落盘报告族，用于非交易日补充说明当天宏观/新闻事件对最近一个开盘日正式综合结论的影响。

边界：

- 只在非交易日生成；第一版先覆盖周末，节假日交易日历后续补强。
- `trade_date` 使用非交易日当天日期，便于按日回看。
- `anchor_trade_date` 指向最近一个开盘日，表示被补充的正式 `final_report / strategy_card` 日期。
- 不生成新的 `final_report`，不生成新的 `strategy_card`，不把补充报告展示成正式交易结论。
- Dashboard 可以同时展示最近开盘日正式结论和当天补充分析，但必须分别标注 `anchor_trade_date` 与 `trade_date`。
- Reports / Report Detail 应把该报告标为“补充分析”，和“综合报告”区分。

建议 artifact 路径：

```text
storage/outputs/macro_event_followup/XAUUSD/<trade_date>/<run_id>/
  source.md
  analysis.md
  report_structured.json
```

建议结构化字段：

- `report_type`: `macro_event_followup`
- `trade_date`: 非交易日当天
- `anchor_trade_date`: 最近开盘日
- `anchor_report_refs`: 上一开盘日 `final_report / strategy_card` 的 report/artifact refs
- `new_macro_events`: 当天新增宏观、新闻和事件输入
- `impact_assessment`: 对上一开盘日结论的强化、削弱、扰动或暂不影响判断
- `watch_items`: 下一个开盘日前需要观察的事件、价位、数据和风险
- `revision_risk`: 是否需要在下一个开盘日前人工复核或重新生成正式综合报告
- `source_refs`: 最新新闻、宏观、Event Flow、原正式报告等来源引用

## 前端展示

文件：

- `apps/frontend-web/src/pages/ReportsPage.tsx`
- `apps/frontend-web/src/pages/ReportDetailPage.tsx`
- `apps/frontend-web/src/adapters/reports.ts`

Report Detail 当前支持：

- artifact 列表
- source
- analysis
- visual
- evidence
- analysis inputs
- source trace

## 风险

- legacy API 和标准 report API 并存，容易出现同一报告多个入口。
- 各报告族的 artifact naming 未完全统一。
- 部分历史产物没有 run_id / snapshot_id。
- Report Detail 需要显式标记 fallback / legacy / unavailable。

## 后续方向

- 每个报告族都登记 `ReportItem`。
- 每个报告族都登记 source / analysis / visual / structured / evidence artifact。
- 所有报告都绑定 `run_id`、`snapshot_id`、`source_refs`、`artifact_refs`。
- Report Detail 只做展示，不做 report 数据拼装。
- `macro_event_followup` 优先走标准 report tables / report detail API，不新增 legacy 专用报告端点。
