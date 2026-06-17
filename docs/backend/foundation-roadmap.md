# 后端底座与前后端接入路线

- Project: finance-agent
- Date: 2026-05-26
- Status: planning baseline
- Scope: backend contract, task observability, source trace, report artifacts, review, data-source status, strategy cards, market chart context, frontend handoff

## 一句话结论

下一阶段先补后端“可追溯底座 + 报告三产物 + 任务状态机 + 数据状态统一”，等 API、Schema、产物路径稳定后，再让 `apps/frontend-web` 分批接入新界面；不要先大规模改前端页面。

对 Jin10 / 网页研究类报告，推荐主链固定为：

```text
网页采集
-> 原始文件归档
-> 文本/图片/表格/图表解析
-> 结构化抽取
-> 证据绑定
-> LLM 分析
-> 审核校验
-> 入库 / 生成报告 / Obsidian 沉淀
```

不要退回成：

```text
网页/PDF -> 直接扔给 LLM -> 输出分析
```

## 总目标

把现有系统从“能跑通”升级为：

```text
可追溯
可复核
可复盘
可前端稳定消费
可支撑策略卡片和可视化报告
```

固定生产主链不变：

```text
api -> scheduler -> worker -> collectors -> parsers -> features -> analysis -> renderer -> output
```

核心目标：

1. 统一后端 Schema / Contract。
2. 强化 `TaskRun` / `TaskStep` 状态机。
3. 固定 `SourceTrace` / `Snapshot` 溯源机制。
4. 固定报告三产物模型：`source.md`、`analysis.md`、`visual.html`，并增加 `report_structured.json`；对 Jin10 图文报告，source 侧还要保留 `vision_layout.json` 作为版面快照。
5. 建立 `ReviewItem` 简版人工复核机制。
6. 为前端 Reports、Agent Tasks、Data Ingestion、Strategy Cards、Market K 线提供稳定 API。
7. 将 `agent_outputs` 固定为页面和报告可消费的一级分析输入层。
8. 增加事实审查 Agent 与综合分析 Agent，分别负责事实一致性审查和跨来源综合分析。

对报告分析链进一步细化为三类 Agent：

1. `Extractor Agent`：只抽取事实，不做判断。
2. `Analyst Agent`：基于解析后内容、结构化事实和证据链做逻辑推演与市场判断。
3. `Auditor Agent`：检查证据绑定、幻觉、遗漏和前后矛盾。

对 Jin10 图文报告补充一条实现约束：

1. 图文解析默认走 `layout-first`，先产出 `vision_layout.json` 的最小 blocks，再由 OpenCV / 二次 OCR / Markdown 渲染生成可读 `raw_article_report.md`。
2. `raw_article_report.md` 必须保留正文与图表对应关系，`agent_analysis_report.md` 必须剔除 `Agent 入库字段` 并突出当日差异，不允许稳定复用固定模板结论。
3. 解析成功的判断不能只看 markdown 文本，必须同时考虑 layout blocks、图表 bbox 与正文锚点。

## 不变边界

- 不改主链，不新增第二套任务主脑。
- 不让前端计算策略、修正数据或补造缺失结论。
- 不让 LLM 替代确定性计算：宏观指标、GEX、WallScore、价格数据、数据源状态必须由确定性逻辑生成。
- 不让 LLM 自由生成最终 HTML；HTML 必须由模板渲染。
- 所有结论必须绑定 `run_id`、`snapshot_id`、`source_refs`、`artifact_refs`。
- 缺失数据必须显式标记为 `unavailable` / `manual_required` / `fallback` 等状态。
- 低置信、对账失败、解析异常、待确认输出必须进入 Review。
- LLM 分析必须消费解析后的 `markdown` / structured facts / chart summaries，不允许直接读取未经解析约束的抓取原文作为唯一输入。
- 事实审查 Agent 不修改 raw、parsed、features 或原始 Agent 输出，只生成审查结果和 ReviewItem。
- 综合分析 Agent 不能替代确定性计算，也不能隐藏事实冲突；它只能汇总已追溯的来源数据、专业 Agent 输出和审查结果。

## 后端分模块开发计划

### Phase 0：冻结工程规则

目标：避免后端底座改造过程中继续发散。

交付：

- 在当前规则文档中确认正式前端是 `apps/frontend-web/src`。
- 确认报告产物采用三产物 + 结构化 JSON。
- 确认前端只读消费后端 API，不计算策略。
- 确认新增接口统一保留 `run_id`、`snapshot_id`、`source_refs`、`artifact_refs`、`warnings`。

验收：

- 新任务包引用本文件和 `AGENTS.md`。
- 不再派发“先大改前端页面但后端契约未稳”的任务。

### Phase 1：Schema / Contract 统一

目标：先让后端、前端、Agent 任务包使用同一套公共语言。

建议新增或整理：

```text
apps/api/schemas/
  common.py
  source_trace.py
  task_run.py
  report.py
  review.py
  strategy.py
  market.py
  data_source.py
  agent_analysis.py
```

核心枚举：

```text
DataStatus:
  live, partial, stale, fallback, mock, unavailable, manual_required

TaskStatus:
  queued, running, success, partial_success, failed, retrying, skipped, degraded, needs_review, cancelled

ArtifactType:
  source_md, analysis_md, visual_html, structured_json, raw_file, parsed_file, feature_json, chart_snapshot

ReviewStatus:
  not_required, pending, approved, rejected, rerun

FactReviewStatus:
  supported, unsupported, contradicted, insufficient_evidence, not_reviewed

SynthesisStatus:
  success, partial, needs_review, unavailable

ReportLifecycleStatus:
  draft, generated, snapshot_bound, needs_review, published, exported, archived
```

必须统一的对象：

```text
SourceRef
ArtifactRef
SnapshotRef
TaskRunResponse
TaskStepResponse
ReportSummary
ReportDetail
ReportArtifact
ReviewItem
StrategyCard
MarketChartContext
DataSourceStatus
AgentOutputSummary
FactReviewResult
SynthesisOutput
ReportAnalysisInput
```

验收：

- 后端公共响应能稳定返回：

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

- 前端 adapter 不需要为每个页面单独猜测状态字段。

### Phase 2：TaskRun / TaskStep 状态机增强

目标：让每一次任务运行都可观察、可重试、可追溯。

模型方向：

```text
TaskRun:
  run_id, task_type, workspace_id, trading_date, status, current_stage,
  progress, started_at, ended_at, total_cost_usd, token_in, token_out,
  snapshot_id, final_result_id, error_summary

TaskStep:
  step_id, run_id, step_name, stage, task_kind, status,
  input_refs, output_refs, source_refs,
  started_at, ended_at, duration_ms, retry_count,
  error_type, error_message
```

阶段映射：

```text
collector, parser, feature, analysis, agent, renderer, knowledge
```

API：

```text
GET  /api/runs
GET  /api/runs/{run_id}
GET  /api/runs/{run_id}/steps
GET  /api/runs/{run_id}/logs
GET  /api/runs/{run_id}/artifacts
POST /api/runs/{run_id}/retry
POST /api/runs/{run_id}/steps/{step_id}/retry
```

验收：

- Agent Tasks 页面能看到当前任务跑到哪一步。
- 每个 step 能看到输入、输出、错误、重试次数和产物路径。
- 失败与降级状态不会被包装成成功。

### Phase 3：SourceTrace / Snapshot 溯源底座

目标：所有结论可以反查来源。

追踪链：

```text
raw file
-> parsed result
-> feature snapshot
-> analysis snapshot
-> agent output
-> fact review output
-> synthesis output
-> report artifact
-> page read model
-> strategy card
```

对象方向：

```text
AnalysisSnapshot:
  snapshot_id, run_id, snapshot_type, data_date, data_status,
  source_refs, feature_refs, created_at

SourceRef:
  source_id, source_name, source_type, data_date, captured_at,
  file_path, sha256, url, status

ArtifactRef:
  artifact_id, artifact_type, file_path, version, generated_at, sha256
```

API：

```text
GET /api/source-trace/{snapshot_id}
GET /api/source-trace/by-report/{report_id}
GET /api/source-trace/by-strategy/{strategy_card_id}
```

验收：

- 任意报告、策略卡、CME 结论都能反查 `run_id`、`snapshot_id`、raw、parsed、feature、agent output、final artifact。

### Phase 3.5：Agent Output 输入层与双 Agent 治理

目标：把 `agent_outputs` 从单纯的任务产物升级为前台页面、报告生成和策略卡复盘都能稳定消费的分析输入层，同时增加事实审查和综合分析两个后处理 Agent。

定位：

```text
deterministic snapshots
-> specialist agent outputs
-> fact_review_agent
-> synthesis_agent
-> report_structured.json / dashboard overview / strategy read model
```

`agent_outputs` 作为输入来源时必须保持：

```text
agent_output_id
agent_name
display_name
module
role
run_id
snapshot_id
input_snapshot_ids
source_refs
artifact_refs
status
bias
confidence
summary
summary_zh
key_findings
risk_points
invalid_conditions
generated_by
model
created_at
```

`fact_review_agent`：

- 输入：确定性快照、source refs、artifact refs、候选 Agent 输出、报告关键段落。
- 输出：`FactReviewResult`，对每条关键结论标记 `supported`、`unsupported`、`contradicted` 或 `insufficient_evidence`。
- 发现事实冲突、来源缺失、日期错配、数值不一致、把 fallback/mock/unavailable 当 live 使用时，必须生成 warning；高影响问题进入 `ReviewItem`。
- 不自动改写原始 Agent 输出，不改 raw/parsed/features。

`synthesis_agent`：

- 输入：确定性快照、所有专业 Agent 输出、fact review 结果、ReviewItem 状态、report artifacts。
- 输出：`SynthesisOutput`，包含综合摘要、共识、分歧、证据链、置信度、降级原因和推荐展示顺序。
- 对 unsupported/contradicted 输入必须降权或排除，并在 warnings 中保留。
- 只生成结构化综合结论和 Markdown 片段；最终 HTML 仍由 renderer 模板渲染。

建议 API：

```text
GET /api/agent-analysis/latest
GET /api/agent-analysis?date=YYYY-MM-DD
GET /api/agent-analysis/run/{run_id}
GET /api/agent-analysis/{agent_output_id}
GET /api/agent-analysis/{agent_output_id}/fact-review
GET /api/agent-analysis/synthesis/latest
GET /api/reports/{report_id}/analysis-inputs
```

建议对象：

```text
FactReviewResult:
  review_id, agent_output_id, run_id, snapshot_id,
  status, checked_claims, unsupported_claims, contradictions,
  source_refs, artifact_refs, warnings, created_at

SynthesisOutput:
  synthesis_id, run_id, snapshot_id, status,
  included_agent_output_ids, excluded_agent_output_ids,
  consensus, disagreements, summary, confidence,
  source_refs, artifact_refs, fact_review_refs, warnings, created_at

ReportAnalysisInput:
  report_id, run_id, snapshot_id,
  deterministic_inputs, agent_outputs,
  fact_reviews, synthesis_outputs, warnings
```

前端消费边界：

- Dashboard：展示综合摘要、事实审查状态、关键 warning 和跳转入口。
- Agent Tasks：展示每个 Agent 的输入、输出、审查结果、证据链、ReviewItem 回链。
- Reports / Report Detail：展示报告引用的 Agent 输出、综合分析来源、事实审查结果。
- Strategy / Event Flow：只消费后端综合 read model，不在页面自行合成最终判断。
- Settings：只管理 prompt governance、密钥和配置状态，不展示 Agent 输出结果。

验收：

- 任意页面或报告使用 Agent Output 时，都能反查来源数据、参与 Agent、事实审查状态和综合分析记录。
- fact review 标记为 unsupported/contradicted 的内容不会被 synthesis 静默使用。
- 事实审查失败不阻断报告生成，但必须让报告或页面状态进入 `partial`、`needs_review` 或 `unavailable`。

### Phase 4：报告三产物模型

目标：固定报告目录、artifact 元数据和 Report Detail API。

标准输出：

```text
storage/outputs/reports/{date}/{report_id}/
  source.md
  analysis.md
  visual.html
  report_structured.json
  metadata.json
  assets/
    screenshot_full.png
    segment_001.png
    segment_002_chart.png
```

建议表：

```text
report_items
report_artifacts
report_segments
report_extractions
report_reviews
```

`report_artifacts` 关键字段：

```text
artifact_id
report_id
artifact_type
file_path
version
model_name
template_version
generated_at
status
sha256
```

生成链路：

```text
raw image/html/pdf
-> OCR/VLM/parser
-> source.md
-> report_structured.json
-> analysis.md
-> visual.html
```

API：

```text
GET  /api/reports
GET  /api/reports/{report_id}
GET  /api/reports/{report_id}/artifacts
GET  /api/reports/{report_id}/source
GET  /api/reports/{report_id}/analysis
GET  /api/reports/{report_id}/visual
GET  /api/reports/{report_id}/evidence
POST /api/reports/{report_id}/regenerate
```

验收：

- 每份新标准报告都有 `source.md`、`analysis.md`、`visual.html`、`report_structured.json`。
- Reports 前端可以分别打开原文、分析、可视化和证据。

### Phase 5：图片报告 OCR / VLM 结构化链路

目标：把图片型报告从随机识别升级为稳定 pipeline。

模块方向：

```text
collectors/report_capture
parsers/report_image
analysis/report_vlm
features/report_structure
renderer/markdown
renderer/html
```

产物方向：

```text
storage/raw/reports/{date}/{report_id}/
  original.html
  screenshot_full.png
  metadata.json

storage/parsed/reports/{date}/{report_id}/
  layout.json
  segments/
  ocr_result.json
  vlm_result.json

storage/features/reports/{date}/{report_id}/
  report_structured.json
  quality_report.json

storage/outputs/reports/{date}/{report_id}/
  source.md
  analysis.md
  visual.html
```

验收：

- 每段内容绑定 `source_segment_id`。
- 低置信内容进入 `ReviewItem`。
- HTML 由模板渲染，不由 LLM 自由生成。

### Phase 6：ReviewItem 简版

目标：把低置信和异常统一收口。

来源：

```text
OCR/VLM 低置信
CME PDF TOTAL 对账失败
TradingView 图表识别异常
LLM 输出置信度低
报告待人工复核
知识规则待复核
数据源需要手工上传
```

对象方向：

```text
ReviewItem:
  review_id, run_id, source_module, source_step_id, severity,
  reason, impact_modules, evidence_refs, suggested_action,
  status, created_at, resolved_at
```

API：

```text
GET  /api/reviews
GET  /api/reviews/{review_id}
POST /api/reviews/{review_id}/approve
POST /api/reviews/{review_id}/reject
POST /api/reviews/{review_id}/rerun
POST /api/reviews/{review_id}/use-fallback
```

验收：

- Agent Tasks 或 Review Center 能统一看到待确认内容、原因、影响模块和可执行动作。

### Phase 7：DataSourceStatus API

目标：让 Data Ingestion 页面吃真实后端状态，而不是静态 mock。

状态：

```text
live, stale, partial, fallback, offline, mock, manual_required
```

对象方向：

```text
DataSourceStatus:
  source_id, source_name, priority, config_status, runtime_status,
  data_status, latest_data_date, last_success_at, last_run_at,
  completeness, latency, affected_modules, fallback_used,
  related_steps, review_items
```

API：

```text
GET  /api/data-sources/status
GET  /api/data-sources/blockers
GET  /api/data-sources/{source_id}
POST /api/data-sources/{source_id}/test
POST /api/data-sources/{source_id}/retry
```

验收：

- Data Ingestion 能真实展示 P0 主链数据源、阻塞项、fallback、manual_required、影响模块和相关 TaskStep。

### Phase 8：StrategyCard API

目标：为 Strategy Cards 页面提供后端数据层；这仍是策略研究与执行剧本，不是自动交易。

对象方向：

```text
StrategyCard:
  strategy_card_id, run_id, snapshot_id, symbol, trading_date,
  bias, market_regime, confidence, main_scenario,
  alternative_scenarios, key_levels, trigger_conditions,
  invalidation_conditions, confirmation_conditions, risk_points,
  source_refs, report_refs, review_status, replay_status
```

API：

```text
GET  /api/strategy-cards
GET  /api/strategy-cards/{strategy_card_id}
POST /api/strategy-cards/generate
POST /api/strategy-cards/{strategy_card_id}/review
```

验收：

- 前端能展示主方案、备选方案、失效条件、关键价位、证据来源和复盘状态。
- 策略卡必须读取 Market Monitor、CME Options、Event Flow、Reports、Data Source 状态，不单独造结论。

### Phase 9：Market K 线 API

目标：支撑 Market Monitor、Strategy Cards、CME Options、Event Flow 的 K 线组件。

表方向：

```text
market_quotes
market_candles
market_levels
market_chart_snapshots
```

API：

```text
GET /api/market/quotes
GET /api/market/candles
GET /api/market/levels
GET /api/market/chart-context
GET /api/market/event-window
```

第一版刷新策略：

```text
quote: 10-15 秒
5m K 线: 30 秒
15m K 线: 60 秒
```

`chart-context` 返回：

```json
{
  "symbol": "XAUUSD",
  "timeframe": "15m",
  "quote": {},
  "candles": [],
  "levels": [],
  "events": [],
  "strategy_zones": [],
  "data_status": "live",
  "source_refs": []
}
```

验收：

- Market Monitor 能显示 XAUUSD 15m K 线、当前价、关键位、数据状态和 `source_refs`。

### Phase 10：Knowledge / Settings 治理 API

目标：把知识条目、规则、配置和诊断纳入后端治理，但不提前影响 P0/P1。

Knowledge 方向：

```text
knowledge_items
knowledge_versions
knowledge_refs
knowledge_reviews
knowledge_agent_rules
```

Settings 方向：

```text
data source config
model config
report template config
knowledge sync config
secret metadata
system diagnostics
```

验收：

- Settings 不返回完整 secret。
- Knowledge 条目能区分 `long_term_valid`、`phase_valid`、`needs_review`、`observing`、`deprecated`、`archived`。

## 优先级

### P0：先做

1. Schema / Contract 统一。
2. TaskRun / TaskStep 状态机。
3. SourceTrace / Snapshot 溯源。
4. Report 三产物模型。
5. Report Detail API。
6. ReviewItem 简版。

### P1：支撑页面闭环

1. Agent Tasks Run 控制台 API。
2. DataSourceStatus API。
3. StrategyCard API。
4. Market chart-context API。

### P2：增强分析能力

1. Event Flow pricing evidence API。
2. CME Options 价位地图 / GEX 分布 API。
3. Market Monitor 四联动 API。
4. Knowledge Agent Rule API。
5. Settings 配置中心 API。

## 前端接入节奏

### 第一批：Reports / Agent Tasks

前置条件：

- 后端稳定提供 `TaskRun`、`TaskStep`、`ReportArtifact`、`SourceTrace`、`ReviewItem`。

前端任务：

1. Reports 卡片增加三产物入口。
2. 新增或完善 `/reports/:report_id`。
3. Agent Tasks 改成 Run 控制台。
4. 标准化 `SourceTracePanel`。

### P0-09 / 第 1.5 批：FinAnalytics Pro 设计系统还原

目标：

- 基于 `docs/frontend/finanalytics-pro-design-system/FinAnalytics_Preview.html` 抽取并实现统一视觉系统和页面布局基础。
- 将 `docs/frontend/finanalytics-pro-design-system/knowledge-base.html` 作为 Knowledge Base 页面专用布局参考。
- 确保后续页面迁移接近最新 FinAnalytics Pro 深色金融终端设计，而不是旧版 placeholder。
- 让所有后续批次同时按“架构正确”和“视觉接近设计稿”验收。

前端任务：

1. 提取颜色 token、背景色、边框色、卡片样式、字体层级、间距、badge、tab、table、right panel、status bar 样式。
2. 对齐现有 Tailwind / CSS 变量，不引入第二套设计系统。
3. 确认 `AppShell / Sidebar / Header / BottomStatusBar / RightPanel` 能承载新设计，但不重写 Shell。
4. 新增或调整共享 UI 组件：`PageHeader`、`MetricCard`、`StatusBadge`、`DataStatusBadge`、`SourceTraceBadge`、`ConvictionBar`、`SectionCard`、`FilterBar`、`RightRailPanel`、`EmptyState`、`WarningBanner`、`MiniSparkline`。
5. 输出《设计系统映射说明》：HTML 设计中的 class / 样式如何映射到当前项目组件，哪些复用现有组件，哪些需要新增，哪些不做 1:1 还原。

验收：

- 不重写 `AppShell`。
- 不引入第二套设计系统。
- 所有页面共享同一套 card / badge / table / tab / status 样式。
- 新页面视觉接近 `FinAnalytics_Preview.html`，而不是旧版 placeholder。
- Knowledge Base 页面额外对照 `knowledge-base.html` 检查三栏/四栏知识工作台布局。
- 每个后续页面批次都必须包含 UI 还原检查。

### 第二批：Data Ingestion / Review Center

前置条件：

- 后端稳定提供 `DataSourceStatus`、`Blocker`、`related_steps`、`review_items`。

前端任务：

1. Data Ingestion 状态语义升级。
2. 阻塞项卡片可操作化。
3. 增加人工复核 tab 或简版 Review Center。

### 第三批：Strategy Cards / K 线

前置条件：

- 后端稳定提供 `StrategyCard`、`MarketChartContext`、`MarketLevels`、`Candles`。

前端任务：

1. 新增 Strategy Cards 页面或模块。
2. 新增 `MarketKlineChart`。
3. 把 K 线接入 Market Monitor、Strategy Cards、CME Options、Event Flow。

## 推荐实际开发顺序

```text
1. 统一后端 schemas/contracts
2. 增强 TaskRun / TaskStep
3. 增强 SourceTrace / Snapshot
4. 实现 Report 三产物模型
5. 实现 Report Detail API
6. 实现 ReviewItem 简版
7. 前端改 Reports + Report Detail
8. 前端改 Agent Tasks
9. 前端 P0-09 / FE-1.5：FinAnalytics Pro 设计系统还原
10. 后端 DataSourceStatus API
11. 前端改 Data Ingestion
12. 后端 StrategyCard API
13. 前端新增 Strategy Cards
14. 后端 Market chart-context API
15. 前端新增 MarketKlineChart
16. 前端把 K 线接入 Market / Strategy / CME / Event
17. 后端 Knowledge / Settings 治理 API
18. 前端改 Knowledge / Settings
19. Backtest / Review 增强
```

## 验收总口径

- 后端新增 API 必须有稳定 schema、显式状态、source/artifact trace。
- 产物必须按 raw / parsed / features / outputs 分层落盘。
- 报告标准产物路径固定，历史报告不被覆盖。
- 前端仅通过 hook + adapter 消费 API，不直接理解复杂后端内部结构。
- 任何缺失、降级、低置信、fallback 都必须在 API 与 UI 中可见。
- 每完成 2-3 个后端模块，先做一次 API/schema 回归，再允许对应前端批次接入。

## UI 还原验收口径

1. 页面必须使用 FinAnalytics Pro 深色金融终端风格。
2. 保留左侧 Sidebar、顶部 Header、底部状态栏、右侧 Context Panel 的整体布局。
3. 页面宽屏下必须接近设计稿三栏结构：左侧导航、中间主内容、右侧上下文面板。
4. 卡片、表格、badge、tab、按钮、状态条必须使用统一共享组件。
5. 不允许每个页面单独写一套视觉样式。
6. mock 数据应尽量接近设计稿内容，用于验证视觉密度。
7. 页面不应出现大面积空白、默认白底、浏览器原生控件风格。
8. 完成每个页面后需要对照 `docs/frontend/finanalytics-pro-design-system/FinAnalytics_Preview.html` 检查布局、信息层级、状态颜色、卡片密度、右侧面板、表格可读性。
9. Knowledge Base 页面还需对照 `docs/frontend/finanalytics-pro-design-system/knowledge-base.html` 检查知识条目列表、详情区、知识图谱和运营面板。

## 前端硬限制

1. 禁止重写 `AppShell / AppSidebar / AppHeader`，除非任务明确允许。
2. 禁止删除现有页面和路由。
3. 禁止在 React 组件中写金融分析计算。
4. 禁止为了还原视觉而硬编码业务结论。
5. 禁止让 mock 状态伪装成真实 `LIVE`。
6. 禁止前端保存 API Key 明文。
7. 禁止一次性改完所有页面。
8. 每个 Batch 必须独立提交、独立验收。
9. 每个 Batch 完成后必须运行 typecheck / lint（如存在）/ build。
10. 页面视觉必须对照 `FinAnalytics_Preview.html`，不是自由发挥。
