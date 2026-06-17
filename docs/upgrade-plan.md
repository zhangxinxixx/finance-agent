# 系统升级与前后端对接开发计划

> 日期：2026-05-28
> 状态：superseded / historical-plan。2026-06-08 起本文只保留为当时升级规划参考，不再作为当前任务入口。
> 输入：`D:\VibeCoding\financial-analysis\docs\架构\260528-系统架构.md`、`docs/frontend/current-frontend-state.md`、当前 `apps/frontend-web/src` 与 FastAPI 路由状态。
> 原则：不新增第二套主脑，不恢复旧前端入口；优先稳定后端 Read Model 和前端契约，再逐页优化。

> 当前入口：最新任务看 `docs/dev/current-task.md`；前端接口事实看 `docs/frontend/api-contract.md`；长期状态看 Obsidian `02-项目/金融分析系统/02-当前进度.md`、`06-任务看板.md`、`04-开发路线图.md`。本文中的 `mock-only`、旧 `/api/final-report*`、旧 `/api/strategy-card*` 和旧 `/api/market/tickers` 表述按历史/兼容口径理解。

## 1. 总体判断

当前系统已经形成核心闭环：

```text
外部数据源
-> collectors
-> raw storage
-> parsers
-> structured snapshots
-> features / analysis
-> source trace / artifacts
-> agent outputs / reports / strategy cards
-> API read model
-> frontend pages
```

下一阶段的关键不是继续增加页面，而是把现有页面接到稳定、可追溯、可降级的后端契约上。

核心执行顺序：

```text
P0 契约与溯源底座
-> P1 页面 Read Model 对齐
-> P2 写操作、配置和高级能力
```

## 2. 当前真实状态

### 2.1 前端入口

正式前端主线是：

```text
apps/frontend-web/src
```

当前路由：

| 路由 | 页面 | 状态 |
|---|---|---|
| `/dashboard` | Dashboard | 已实现，接 `/api/dashboard/summary` 等 |
| `/data-ingestion` | Data Ingestion | 已实现，接 `/api/data-sources/status`、`/api/data-status/summary` |
| `/event-flow` | Event Flow | 已实现，当前 mock-only |
| `/market-monitor` | Market Monitor | 已实现，接 `/api/market/tickers`、`/api/macro/latest` |
| `/cme-options` | CME Options | 已实现，接 `/api/options/dates`、`/api/options/snapshot` |
| `/reports` | Reports | 已实现，接 reports/final/options/jin10 family APIs |
| `/reports/:reportId` | Report Detail | 已实现，接 `/api/reports/{report_id}` |
| `/knowledge-base` | Knowledge Base | 已实现，当前 mock-only |
| `/agent-tasks` | Agent Tasks | 已实现，接 `/api/runs*`、`/api/reviews` |
| `/agent-analysis` | Agent Analysis | 后续候选独立页；也可先并入 `/agent-tasks` 详情，展示 Agent 输出、事实审查和综合分析 |
| `/settings` | Settings | 已实现，当前 mock-only |
| `/strategy` | Strategy Center | 已新增只读入口，接 `useStrategy()`；Dashboard 跳转、后端历史/详情 read model、前端历史/详情消费已完成，后端 Playbook 聚合待补 |

禁止恢复或新增第二套入口：

- `apps/frontend/`
- `apps/frontend-web/dashboard.html`

### 2.2 已有后端 API

当前 FastAPI 已有主要端点：

| 领域 | 当前端点 |
|---|---|
| Dashboard | `GET /api/dashboard/summary` |
| Data status | `GET /api/data-sources/status`、`GET /api/data-status/summary` |
| Runs / tasks | `GET /api/runs`、`GET /api/runs/{run_id}`、`GET /api/runs/{run_id}/steps`、`GET /api/runs/{run_id}/logs`、`GET /api/runs/{run_id}/artifacts` |
| Reviews | `GET /api/reviews`、`POST /api/reviews/{review_id}/approve` 等 |
| CME Options | `GET /api/options/dates`、`GET /api/options/snapshot`、`GET /api/options/visual-report*` |
| Macro / market | `GET /api/macro/latest`、`GET /api/market/tickers` |
| Reports | `GET /api/reports/index`、`GET /api/reports/dates`、`GET /api/reports/{report_id}`、artifact/source/analysis/visual/evidence 子端点 |
| Source trace | `GET /api/source-trace/{snapshot_id}`、`GET /api/source-trace/by-report/{report_id}`、`GET /api/source-trace/by-strategy/{strategy_card_id}` |
| C4 reports | `GET /api/final-report*`、`GET /api/strategy-card*` |
| Strategy | `GET /api/strategy-card/latest`、`GET /api/strategy-card?date&run_id`；兼容 read model：`GET /api/strategy-cards`、`GET /api/strategy-cards/{id}`、`GET /api/strategy-cards/latest` |
| Agent analysis | `GET /api/agent-analysis/latest`、`GET /api/agent-analysis?date=...`；后续补 `GET /api/agent-analysis/run/{run_id}`、`GET /api/agent-analysis/{agent_output_id}`、fact review 和 synthesis read model |
| Jin10 | `GET /api/jin10/daily-report*`、`GET /api/jin10/report-bundle*`、`GET /api/jin10/weekly-report*` |
| Market odds | `GET /api/market-odds/snapshot`、`GET /api/market-odds/report` |

因此，升级计划不应直接引入一批全新路径替代现有 API；应先扩展现有端点字段，必要时再新增兼容型 overview read model。

## 3. 统一契约

### 3.1 PageEnvelope

所有页面级 adapter 最终应归一到同一种 envelope 语义：

```ts
type PageEnvelope<T> = {
  status: "available" | "partial" | "unavailable" | "error";
  source: "api" | "mock" | "unavailable";
  data: T | null;
  trace: {
    snapshot_id?: string | null;
    run_id?: string | null;
    source_refs: SourceRef[];
    artifact_refs: ArtifactRef[];
    dataDate?: string | null;
    asOf?: string | null;
  };
  warnings: Array<{
    code: string;
    message: string;
    severity: "info" | "warn" | "error";
  }>;
  fallback_reason?: string | null;
};
```

### 3.2 标准状态

| 类型 | 标准值 |
|---|---|
| 数据可用性 | `LIVE` / `PARTIAL` / `MOCK` / `UNAVAILABLE` |
| 页面状态 | `available` / `partial` / `unavailable` / `error` |
| 任务状态 | `queued` / `running` / `success` / `partial_success` / `failed` / `retrying` / `skipped` / `degraded` / `needs_review` / `cancelled` |
| 事件定价状态 | `PRICED` / `PARTIAL` / `UNPRICED` / `REVERSED` |
| 事件传导状态 | `confirmed` / `inferred` / `pending` |
| 数据新鲜度 | `REALTIME` / `FRESH` / `STALE` / `EXPIRED` / `MISSING` |
| 分析影响 | `NONE` / `LOW` / `MEDIUM` / `HIGH` / `BLOCKING` |

### 3.3 前端约束

- Page 不直接 `fetch` raw API。
- Page 不做市场策略推导。
- Hook 只负责加载生命周期。
- Adapter 负责 raw API -> ViewModel 归一化。
- Mock fallback 必须显式显示 `source: "mock"` 和 `fallback_reason`。
- 缺失数据保留 `unavailable`，不补造默认结论。

## 4. P0：契约、入口和溯源底座

目标：不重做页面，不大改视觉；先让页面“知道自己展示的数据来自哪里、是否可信、缺什么”。

### P0-01：前端入口与路由收口

问题：

- `LoginPage.tsx` 存在但未路由。
- `PlaceholderPage.tsx` 被 import 但未使用。
- Vite SPA fallback 未覆盖 `/reports/:reportId`。

任务：

- 修复 Vite fallback，支持动态详情路由刷新。
- 明确 `LoginPage`：本阶段不做权限则删除或归档；若保留则注册明确路由和认证边界。
- 明确 `PlaceholderPage`：未使用则移除 import，避免误导。
- 保持 `/dashboard` 后端兼容跳转，不恢复直出 HTML。

验收：

- `http://localhost:8080/reports/<id>` 直接刷新能进入 SPA。
- `main.tsx` 中没有未使用页面导入。

### P0-02：共享 PageEnvelope 与状态类型

任务：

- 在 `apps/frontend-web/src/types/` 增加或整理共享 envelope/source trace/artifact/status 类型。
- 对齐 `LIVE/PARTIAL/MOCK/UNAVAILABLE` 与页面 `available/partial/unavailable/error`。
- 在 `lib/status.ts` 中固定 tone 映射。

验收：

- adapters 不再各自定义互相冲突的 status 字符串。
- 页面能统一渲染 loading/error/empty/partial。

### P0-03：Mock / Live 边界显式化

任务：

- 所有有 mock fallback 的 adapter 返回 `source`。
- 所有 mock fallback 返回 `fallback_reason`。
- 页面显式展示 `实时接口` / `本地回退` / `不可用`。

优先页面：

1. Dashboard
2. Data Ingestion
3. Market Monitor
4. CME Options
5. Agent Tasks
6. Reports

验收：

- API 失败而使用 mock 时，页面不能表现为 Live。
- `npm run typecheck` 通过。

### P0-04：Reports / Agent Tasks / Data Ingestion 三个底座页优先

原因：

- Reports 管 artifacts。
- Agent Tasks 管 run / step / logs。
- Data Ingestion 管 source health。

任务：

- Reports index/detail 补 `report_id`、`family`、`snapshot_id`、`run_id`、`data_status`、`source_refs`、`artifact_refs`。
- Agent Tasks 补 `source_refs`、`artifact_refs`、`final_result_id`、`error_type`、`retry_count` 一致展示。
- Data Ingestion 补 `freshness`、`analysisImpact`、`missing_sources`、collector-level status。

验收：

- 三个页面都能回答：数据来自哪里、哪个 run 生成、缺失什么、是否影响分析。

### P0-05：后端字段兼容扩展

任务：

- 优先扩展现有端点，不先替换路径。
- 后端 routes 保持轻逻辑，聚合逻辑放 service/repository。
- 所有新增字段保持 optional，避免破坏前端现有消费。

重点端点：

```text
/api/reports/index
/api/reports/{report_id}
/api/runs*
/api/data-sources/status
/api/data-status/summary
/api/dashboard/summary
```

验收：

- 旧前端字段不破坏。
- 新字段可被前端 adapter 消费。

## 5. P1：页面 Read Model 对齐

目标：逐页把“前端拼业务含义”迁到后端 read model 或 analysis result。

### P1-01：Dashboard Overview

当前：

- 使用 `/api/dashboard/summary`、strategy card、report dates、dashboard mock。

目标：

- Dashboard 只保留总控和摘要，不承载完整子页面。
- 后端可新增 `GET /api/dashboard/overview/latest`，但初期应作为 `/api/dashboard/summary` 的兼容聚合层。

模块：

- 今日状态总控。
- 6 个核心 KPI。
- Market / CME / Event / Report 摘要入口。
- 风险和数据状态。

验收：

- Dashboard 不前端推导 bias。
- 所有 summary block 有 trace/status。

### P1-02：CME Options Read Model

当前：

- `/api/options/dates`
- `/api/options/snapshot`

补强字段：

- Put/Call GEX Ratio。
- WallScore top levels。
- Gamma Zero。
- 主战区、主墙位、转强门槛、修复目标、失效区。
- support/resistance 明确分层。
- `data_source.status` 保持 FINAL/PRELIM。

验收：

- 前端只展示后端计算结果，不重算 Black-76/GEX。
- mock/unavailable 状态明确。

### P1-03：Market Monitor Diagnosis

当前：

- `/api/market/tickers`
- `/api/macro/latest`

目标 read model：

```ts
type MarketDiagnosis = {
  marketRegime: string;
  primaryDriver: string;
  secondaryDriver: string;
  pressureFactor: string;
  divergenceAlert: string;
  tradeWarning: string;
  invalidationCondition: string;
};
```

可选端点：

- `GET /api/market/diagnosis`
- 或 `GET /api/market-monitor/overview`

验收：

- 当前市场诊断由后端返回。
- 前端 heatmap/table 只展示和解释字段，不生成交易结论。

### P1-04：Event Flow 从 mock 迁到 read model

当前：

- `adapters/eventFlow.ts` mock-only。

目标端点：

- `GET /api/events/flow/overview`

ViewModel：

- timeline
- chain
- sentiment
- radar
- impact_assets
- reports
- source_trace

补强：

- 每个传导步骤有 `confirmed/inferred/pending`。
- 定价状态有 `PRICED/PARTIAL/UNPRICED/REVERSED`。
- 事件可信度用数值和来源质量，不只用星级。

### P1-05：Reports 标准化

当前：

- Reports 已有 index/detail/family APIs，但 family 状态较复杂。

任务：

- 报告卡固定字段：
  - report_id
  - family
  - type
  - title
  - trade_date
  - run_id
  - snapshot_id
  - lifecycle_status
  - review_status
  - data_status
  - summary
  - source_refs
  - artifact_refs
- `/reports/:reportId` 作为标准详情入口，family API 作为兼容来源。

验收：

- 列表点击不依赖临时 `type/date/run_id` 拼接。
- 详情页四类 artifact tab 可显示 available/unavailable。

### P1-06：Knowledge Base 只读接入

当前：

- mock-only。

目标端点：

- `GET /api/knowledge/items`
- `GET /api/knowledge/items/{id}`

知识类型：

```ts
type KnowledgeType =
  | "RESEARCH_NOTE"
  | "METHOD_FRAMEWORK"
  | "STRATEGY_PLAYBOOK"
  | "AGENT_RULE"
  | "DATA_DICTIONARY"
  | "REPLAY_CASE"
  | "PROMPT_TEMPLATE"
  | "SYSTEM_CONSTRAINT";
```

验收：

- 知识页只读接入 Obsidian/DB 索引。
- 不允许前端或 Agent 直接写生产规则。

### P1-07：策略中心（Strategy Center）

当前问题：

- 策略散落在 Dashboard（摘要卡）、Reports（策略报告）、Knowledge Base（Playbook）、CME Options（结构策略），无独立管理入口。
- 后端已有 `StrategyCard` schema（含 main_scenario、alternative_scenarios、key_levels、trigger_conditions、invalidation_conditions、confirmation_conditions、risk_points、review_status、replay_status）和单数 C4 端点 `/api/strategy-card/latest`、`/api/strategy-card?date&run_id`，但前端仅在 Dashboard adapter 中消费。
- 缺少策略历史对比、Playbook 模板管理、策略复盘闭环。

定位：

> 策略中心是系统“策略卡查看与复盘”的统一出口。它不在前端计算交易判断，而是展示后端 `StrategyCard`、SourceTrace、报告引用、模块诊断和 Playbook 匹配结果。

边界修正：

- P1 先做只读策略中心 MVP，不做前端策略生成。
- `SignalConvergence` 只展示后端返回的模块摘要；Market / CME / Event / Knowledge 任一 read model 未完成时显示 `unavailable`。
- Playbook 匹配逻辑必须在后端 read model / analysis service 中完成，前端只展示匹配结果和引用。
- “一键生成报告”“策略复盘写回”“模板管理写操作”后置到 P2，不进入 P1 MVP。

页面结构：

| 区域 | 内容 | 数据来源 |
|---|---|---|
| 顶部总控 | 当日策略卡：bias、direction、confidence、market_regime | `/api/strategy-card/latest` |
| 主方案区 | main_scenario + alternative_scenarios + key_levels + trigger / invalidation / confirmation / risk_points | StrategyCard |
| 信号汇聚 | Market Monitor 诊断 + CME 结构状态 + Event Flow 未定价事件 | 后端 strategy overview 中的 module_signals；缺失则 unavailable |
| Playbook 匹配 | 当前市场状态匹配的 Playbook 模板 | 后端返回的 playbook_matches；不在前端匹配 |
| 历史策略 | 近 N 日策略卡列表 + 复盘状态 | 已接入后端 `/api/strategy-cards` read model，支持列表与详情切换 |
| 右侧溯源 | source_refs、snapshot_id、run_id、data_quality、evidence_refs | StrategyCard.trace |

端点计划：

| 端点 | 用途 |
|---|---|
| `GET /api/strategy-card/latest` | 现有单数端点，P1 MVP 先消费 |
| `GET /api/strategy-card?date&run_id` | 现有单数端点，P1 MVP 可用于详情兜底 |
| `GET /api/source-trace/by-strategy/{strategy_card_id}` | 现有溯源端点，P1 MVP 接入 |
| `GET /api/strategy-cards` | 已新增兼容 read model：策略卡历史摘要列表，支持 `asset`、`limit` |
| `GET /api/strategy-cards/{id}` | 已新增兼容 read model：单张策略卡详情，支持 `strategy_card_id` / `run_id` / `snapshot_id` 查找 |
| `GET /api/strategy-cards/latest` | 已新增兼容 read model：最新策略卡详情；module_signals / playbook_matches 聚合后续接入 |

前端新增：

```
src/pages/StrategyPage.tsx
src/components/strategy/
  StrategyHeroCard.tsx        — 当日策略总控卡
  ScenarioPanel.tsx           — 主方案 + 备选方案
  SignalConvergence.tsx       — 多模块信号汇聚
  PlaybookMatch.tsx           — 匹配的 Playbook 模板
  StrategyHistory.tsx         — 历史策略列表
  StrategyTracePanel.tsx      — 溯源面板
src/hooks/useStrategy.ts
src/types/strategy.ts
src/adapters/strategy.ts
```

与现有模块关系：

| 模块 | 策略中心关系 |
|---|---|
| Dashboard | 只展示策略卡摘要，点击跳转策略中心详情 |
| Market Monitor | 输出 marketRegime / primaryDriver / divergenceAlert，策略中心消费 |
| CME Options | 输出结构状态 / Gamma Zero / 主墙位，策略中心消费 |
| Event Flow | 输出未定价高影响事件，策略中心评估是否调整策略 |
| Knowledge Base | 输出 STRATEGY_PLAYBOOK 模板，策略中心匹配当前市场状态 |
| Reports | P1 只做报告回链策略卡；一键生成报告后置 P2 |

实施切片：

| 切片 | 范围 | 验收 |
|---|---|---|
| P1-07a-1 Strategy 数据层 | 新增 `types/strategy.ts`、`adapters/strategy.ts`、`hooks/useStrategy.ts`、`mocks/strategy.json`，先消费现有 `/api/strategy-card/latest`，失败时显式 mock fallback | `npm run typecheck`、`npm run build` 通过；API 成功不被误判为 unavailable；无前端策略计算 |
| P1-07a-2 Strategy 页面入口 | 新增 `/strategy` 路由、Sidebar 入口、只读页面，调用 `useStrategy()` 展示当日策略卡、scenario、module_signals、playbook_matches、source_refs / artifact_refs | `npm run typecheck`、`npm run build`、`git diff --check` 通过；mock 明确标识；无前端策略计算 |
| P1-07a-3 Dashboard 跳转与收口 | 已在 Dashboard 顶部跳转按钮组增加 `/strategy` 入口，不复制策略详情页 | `npm run typecheck`、`npm run build`、`git diff --check` 通过；Dashboard 只保留入口；不新增策略推导 |
| P1-07b-1 Strategy read model API | 已新增 `/api/strategy-cards*` 历史/详情/最新兼容端点，保留单数端点兼容 | `pytest tests/api/test_analysis_db_api.py -q`、`pytest tests/api/test_c4_reports_api.py -q`、route smoke、`py_compile`、`git diff --check` 通过；不破坏现有 `/api/strategy-card/latest` |
| P1-07b-2 Strategy 历史前端消费 | 已将 `/strategy` 页面从单张 latest 扩展到历史列表/详情切换，继续保持只读 | `npm run typecheck`、`npm run build`、`git diff --check` 通过；复数端点失败回落单数 latest，再失败回落 mock；不在前端生成策略 |
| P1-07c Module signals | 后端聚合 Market / CME / Event 诊断状态为 `module_signals` | 缺失模块显示 `unavailable`，前端不拼接业务结论 |
| P1-07d Playbook matches | 后端按 Knowledge Base `STRATEGY_PLAYBOOK` 输出匹配结果和引用 | 前端只展示 match score、rule id、source refs |

验收：

- 策略中心可展示当日策略卡 + 溯源信息。
- 历史策略列表可按日期浏览。
- 策略卡每个字段都有 source_refs 可追溯。
- Dashboard 策略摘要点击可跳转策略中心。
- 前端不能出现策略推导函数或 Playbook 匹配规则。

### P1-00：统一 P1 Read Model 口径

目标：在 P1 各页面实现前，先统一 Strategy / Event Flow / Knowledge / Settings 的 ViewModel 最小字段集和状态映射，避免页面 adapter 各自造类型。

复用基础类型：

- `PageEnvelope<T>`（`types/page-envelope.ts`）：通用页面数据信封。
- `SourceRef`（`types/common.ts`）：溯源引用。
- `ArtifactRef`（`types/artifact.ts`）：产物引用。
- `DataStatus`（`types/common.ts`）：`"available" | "partial" | "unavailable" | "error"`。
- `DataAvailability`（`types/common.ts`）：`"LIVE" | "PARTIAL" | "MOCK" | "UNAVAILABLE"`。

P1 页面最小 ViewModel 字段表：

| 页面 | ViewModel 类型 | 核心字段 | 当前实现要求 |
|---|---|---|---|
| Strategy | `StrategyViewModel` | status, source, hero, scenario, module_signals, playbook_matches, artifact_refs, source_refs, has_data | 新增类型，后续 `/strategy` 页面只消费该模型 |
| Event Flow | `EventFlowViewModel` | status, source, timeline, chain, sentiment, radar, table, source_refs, has_data | 当前 mock-first，source_refs 可暂缺；后端 read model 补齐后必须返回 |
| Knowledge | `KnowledgeViewModel` | status, source, items, selectedItem, stats, source_refs, has_data | 当前 mock-first，status/source/source_refs 可暂缺；后端 read model 补齐后必须返回 |
| Settings | `SettingsViewModel` | status, source, sources, globalConfig, systemInfo, source_refs, has_data | 新增只读类型，不包含明文密钥，不做写配置 |

状态映射规则（mock/live/unavailable）：

| 后端 source | DataStatus | DataAvailability | 前端展示 |
|---|---|---|---|
| `api` + 有数据 | `available` | `LIVE` | 正常展示，状态条显示 Live |
| `api` + 部分缺失 | `partial` | `PARTIAL` | 展示已有数据，缺失区域标注 unavailable |
| `mock` | `available` | `MOCK` | 展示数据，状态条显示 Mock / 本地回退 |
| `fallback` | `partial` | `PARTIAL` | 展示可用数据，同时标注降级原因 |
| `unavailable` | `unavailable` | `UNAVAILABLE` | 不补造数据，展示不可用提示 |
| `error` | `error` | `UNAVAILABLE` | 展示错误和重试入口 |

职责边界：

- Strategy 不在前端计算 bias / confidence / Playbook 匹配。
- Event Flow 不在前端推导事件影响或传导链。
- Knowledge 不在前端生成规则、评分或 agent-ready 判断。
- Settings P1 只读，不做密钥写入、配置保存或权限系统。

## 6. P2：写操作、配置和高级能力

P2 必须等 P0/P1 稳定后再做。2026-05-29 的执行基线是：P1 read model 已闭环，P2 先冻结 action contract，再做 Review 前端消费和写操作硬化；所有写操作必须可审计、可回滚、绑定 run/source/artifact，不允许引入第二套任务主脑。

2026-05-30 状态：P2-00~P2-03 已完成首轮开发与验收；P2-04 Settings 写配置已完成第三批收口，当前继续收敛审计页和 runtime secret 注入边界，后者已从 Jin10 扩展到 FRED/DashScope/Mem0。

2026-05-31 补充方向：P2 后续增加 Agent Output 输入层、事实审查 Agent 和综合分析 Agent。Agent 输出可以作为 Dashboard、Strategy、Event Flow、Reports、Report Detail 的 read model 输入，但必须经由后端 schema/service 暴露，不允许前端直接拼业务结论。

### P2-00：Contract Audit

目标：冻结 P2 写操作和高级能力的 API/action 契约，避免前端先接按钮、后端再补语义。

交付：

- Action envelope：`actor`、`action`、`reason`、`request_id`、`run_id`、`source_refs`、`artifact_refs`、`audit_id`、`status`、`error`。
- 页面到 API 映射：Review Center、Data Ingestion、Settings、Knowledge/Playbook、Strategy。
- 失败状态表：无权限、目标不存在、状态冲突、任务已运行、artifact 缺失、schema 校验失败。

验收：

- 每个 P2 写操作都有明确 endpoint、request、response、失败状态。
- 标明哪些 action 只写审计，哪些必须创建 `task_run`。
- 文档明确前端不得直接写 artifact / raw / parsed / features。

状态：已完成。前端契约文档已补 action envelope、failure states、page-to-API map 和 ActionState ViewModel。

### P2-01：Review Center 只读消费

目标：把已有 `ReviewItem` 后端闭环稳定暴露到前端消费界面，先做过滤、详情、溯源和空状态，不做 approve/reject/rerun。

当前基线：

- 后端已有 `GET /api/reviews`、`GET /api/reviews/{review_id}`。
- `Agent Tasks` adapter 已能读取 `/api/reviews?status=pending&run_id=...`。
- 独立 Review Center 或 Agent Tasks 内 Review 工作台仍需产品化验收。

验收：

- API 可用时 `source: api`，API 不可用时 mock/unavailable 明确标识。
- pending 为空时显示空状态，不造假数据。
- Review 详情不触发任何写操作。

状态：已完成。新增 `/review-center` 只读页面和 Sidebar 入口，P2-02 前不接写按钮。

### P2-02：Review approve / reject / rerun hardening

目标：把已有 Review action 从“能改状态”加固为“可审计、可回滚、可主链回流”的生产语义。

已有：

- `POST /api/reviews/{review_id}/approve`
- `POST /api/reviews/{review_id}/reject`
- `POST /api/reviews/{review_id}/rerun`
- `POST /api/reviews/{review_id}/use-fallback`

补强：

- 权限。
- 审计。
- 回滚。
- 状态冲突。
- `rerun` 回到 scheduler / worker 主链；未接通时返回 `manual_required` 或 `queued_not_implemented`，不能伪造已重跑。

状态：已完成。Review action request/response 已补 actor、reason、request_id、expected_status、audit_id、action_status、next_run_id；状态冲突返回 409，rerun 当前返回 `queued_not_implemented`。

### P2-03：Data Ingestion retry / manual upload

候选端点：

- `POST /api/ingestion/sources/{id}/retry`
- `POST /api/ingestion/manual-upload`

要求：

- retry 每次操作生成 `run_id`。
- manual upload 只写 raw 或 staging，标记 `source_type: manual`、`data_status: manual_required|partial`。
- 产物进入 raw/parsed/features/outputs 分层，不混写。
- UI 只展示任务状态，不直接改 raw 数据。

状态：已完成。新增 retry/manual-upload 后端 action，均创建 `task_run/task_step`；Data Ingestion 页面新增 retry 操作入口，manual upload 前端文件控件暂不接入。

### P2-04：Settings 写配置

目标：在 P1 只读 Settings 基础上，谨慎增加可审计配置写入能力，优先处理低风险开关，再处理密钥。

写操作候选：

- 非敏感配置：默认语言、时区、报告模板选择、数据源 enable/disable 请求。
- 密钥配置：只允许写入安全存储或明确标记 `not_implemented`。
- 敏感字段只返回 `masked`、`configured`、`last_updated_at`。

要求：

- 先写 ADR 和 schema。
- 不允许 API 返回密钥明文。
- 不直接修改 `.env` 作为默认实现。
- Settings 不承担运行诊断，运行状态仍归 Data Ingestion / Agent Tasks。

状态：第三批收口已完成。已新增 `app_settings` portable DB 配置表、append-only `app_setting_events` 审计事件、`app_secrets` encrypted secret storage、`POST /api/settings/preferences`、`POST /api/settings/preferences/reset`、`POST /api/settings/sources/{source_key}`、`POST /api/settings/sources/{source_key}/reset`、`POST /api/settings/secrets/{source_key}`、`POST /api/settings/secrets/{source_key}/reset`、`GET /api/settings/history`、`POST /api/settings/history/{audit_id}/rollback`、`/api/settings/status` DB overlay，以及 `/settings` 最小写入口/历史展示；独立审计页已补齐。当前 secret write 依赖 `SETTINGS_MASTER_KEY`，API 只返回 masked/configured/timestamp 元数据；Jin10 MCP/data_layer 已先行支持 env/.env/DB secret fallback，FRED / DashScope / Mem0 也已接入同一 runtime secret 解析层。剩余工作转为验证 scheduler/worker 更广联动和后续新 consumer 的接入规范。

### P2-05：Playbook 模板管理

目标：把 Playbook 从只读匹配结果推进到可版本化模板管理，但 Strategy 匹配仍由后端 read model / analysis service 执行。首版已完成模板登记与只读浏览，发布/人工确认流程留给后续扩展。

模板字段：

- `playbook_id`
- `version`
- `status`
- `conditions`
- `actions`
- `invalidations`
- `source_refs`
- `last_validated`

边界：

- 不在前端做 Playbook 匹配。
- 不让未发布模板进入 StrategyCard 生产匹配。
- 不直接写 Obsidian / Mem0 / 向量库作为默认生产路径。

状态：首版已完成。当前已落地 `playbook_templates` portable DB 表、`GET /api/playbooks`、`GET /api/playbooks/{playbook_id}`、`GET /api/playbooks/{playbook_id}/versions`、`POST /api/playbooks`，以及 `/knowledge-base` 下的 Playbook registry 浏览区；模板历史只读展示，不影响 Strategy 匹配结果。

### P2-06：多资产和历史校准

内容：

- 资产配置化。
- 历史样本库。
- Playbook 命中率。
- 策略卡历史验证。

状态：首个前端筛选切片已完成。`/strategy` 现在可按资产 / 时间窗口 / regime 过滤历史样本，并在样本不足时显式显示 unavailable/partial；资产级校准概览和历史详情都已回推后端 regime 分布；后续如果继续扩展历史样本库或更多资产，再单独开新切片。

边界：

- 不改变当前默认 `XAUUSD` 查询结果。
- 不把校准指标写成前端计算。
- 不用不完整历史样本生成确定性胜率结论。
- 不自动交易。
- 不引入第二套实时主脑。

### P2-07：P2 集成实测与文档收口

目标：每完成 2-3 个 P2 切片后做一次端到端实测和文档同步，防止写操作与前端状态漂移。

验收：

- 隔离端口启动 API 和 Vite 前端。
- 覆盖 `/agent-tasks` 或 `/review-center`、`/data-ingestion`、`/settings`、`/knowledge-base`、`/strategy`。
- 桌面和移动视口无横向溢出。
- console/pageerror/network failure 为 0，或有明确已知原因。
- Obsidian 版本记录追加 P2 实测结果。

状态：已完成首轮隔离端口实测。`http://127.0.0.1:8001` 后端和 `http://127.0.0.1:5174` 前端已通过浏览器冒烟验证，覆盖 `/strategy`、`/settings`、`/settings/audit`、`/knowledge-base`、`/review-center`、`/data-ingestion`、`/agent-tasks` 的桌面与移动视口，未见横向溢出、pageerror 或网络失败。

### P2-08：Agent Output 输入层

目标：把 `agent_outputs` 从任务详情产物提升为页面和报告可复用的分析输入来源。

交付：

- 新增或整理 `apps/api/schemas/agent_analysis.py`。
- 新增 `apps/api/services/agent_analysis_service.py`，把 display label、本地化 summary、事实审查状态和综合分组从 route/page 中移出。
- 扩展 `GET /api/agent-analysis/latest`、`GET /api/agent-analysis?date=...`，补 `GET /api/agent-analysis/run/{run_id}`、`GET /api/agent-analysis/{agent_output_id}`。
- 补 `GET /api/reports/{report_id}/analysis-inputs`，让 Report Detail 能展示报告引用的 deterministic inputs、Agent outputs、fact reviews 和 synthesis outputs。
- 前端新增 `AgentAnalysisViewModel`，由 adapter 统一消费；Dashboard 只展示摘要，完整详情进入 `/agent-tasks` 或候选 `/agent-analysis`。

边界：

- Agent Output 必须带 `run_id`、`snapshot_id`、`source_refs`、`artifact_refs`、`input_snapshot_ids`。
- Settings 不展示 Agent 输出结果，只管 prompt/config/secret governance。
- 页面只展示后端 ViewModel，不在 React 组件里汇总最终判断。

验收：

- Dashboard、Strategy、Event Flow 或 Reports 至少一个页面通过 adapter 消费 Agent Output 摘要。
- Report Detail 能列出本报告使用的 Agent 输出及其审查状态。
- API 字段中英显示稳定，不再靠 route 或页面正则临时翻译。

### P2-09：事实审查 Agent 与综合分析 Agent

目标：在专业 Agent 输出之后增加两个治理型后处理 Agent。

`fact_review_agent`：

- 输入：source refs、artifact refs、确定性快照、候选 Agent 输出、报告关键段落。
- 输出：`FactReviewResult`，逐条标记 `supported` / `unsupported` / `contradicted` / `insufficient_evidence`。
- 发现 unsupported/contradicted 时生成 warning；高影响问题进入 ReviewItem。
- 不改写原始 Agent 输出，不改 raw/parsed/features。

`synthesis_agent`：

- 输入：确定性数据、各专业 Agent 输出、fact review 结果、ReviewItem 状态和报告 artifact。
- 输出：`SynthesisOutput`，包含综合摘要、共识、分歧、证据链、置信度、降级原因和推荐展示顺序。
- 对 unsupported/contradicted 输入降权或排除，并在 warnings 中显式保留。
- 只生成结构化综合结论和 Markdown 片段，最终 HTML 仍由 renderer 模板渲染。

验收：

- 每条综合结论能反查参与的 Agent 输出、source refs 和 fact review 结果。
- fact review 的 unsupported/contradicted 不会被 synthesis 静默吞掉。
- 事实审查失败不阻断报告生成，但报告或页面状态必须降级为 `partial`、`needs_review` 或 `unavailable`。

## 7. 开发执行顺序

```text
Phase 0: 当前 diff 收口
  1. review 当前未提交 frontend/docs diff
  2. npm run typecheck
  3. npm run build
  4. 判断 docs/superpowers/ 是否属于本任务

Phase 1: P0 契约底座
  1. 路由/fallback/未使用页面清理
  2. PageEnvelope + status 类型
  3. Mock/Live 显式化
  4. Reports / Agent Tasks / Data Ingestion 字段对齐
  5. 后端现有 API optional 字段扩展

Phase 2: P1 Read Model
  1. Dashboard overview
  2. CME Options 结构化字段
  3. Market diagnosis
  4. Event Flow API
  5. Reports 标准 detail
  6. Knowledge read-only API
  7. Strategy Center（先只读策略卡 MVP，再分阶段补历史 API、module_signals、后端 Playbook 匹配结果）

Phase 3: P2 写操作和高级能力
  0. Contract Audit
  1. Review Center 只读消费
  2. Review action hardening
  3. Data Ingestion retry / manual upload
  4. Settings 写配置
  5. Playbook 模板管理
  6. 多资产和历史校准
  7. P2 集成实测与文档收口
```

## 8. 验收矩阵

| 范围 | 验收 |
|---|---|
| 前端类型 | `cd apps/frontend-web && npm run typecheck` |
| 前端构建 | `cd apps/frontend-web && npm run build` |
| API 基础 | `/health`、`/api/dashboard/summary`、`/api/reports/index`、`/api/runs` |
| Reports | 列表、详情、artifact tabs、source trace |
| Agent Tasks | run list、step timeline、logs、artifacts、reviews |
| Agent Analysis | Agent 输出输入链、fact review、synthesis、report analysis inputs |
| Data Ingestion | source status、missing sources、freshness、blocking impact |
| Strategy Center | P1-07a：当日策略卡、source trace、trigger / invalidation / risk_points；P1b+：历史列表、module_signals、Playbook 匹配结果 |
| Mock 边界 | 断开 API 时页面显示 mock/unavailable，不显示 Live |
| 路由 | 直接刷新 `/dashboard`、`/reports`、`/reports/:reportId` |

## 9. 关键风险

| 风险 | 控制方式 |
|---|---|
| 新增 overview API 导致旧 API 和新 API 双轨 | 先扩展现有端点，overview 只作为兼容聚合层 |
| Mock 掩盖真实错误 | 强制显示 `source` 和 `fallback_reason` |
| 前端继续推导策略 | 业务结论全部来自后端 read model / analysis result |
| Agent 边界扩大 | Agent 只读 snapshot/artifact，不改 raw/parsed/features |
| 综合分析吞掉事实冲突 | fact review 的 unsupported/contradicted 必须进入 warnings 和 ReviewItem，synthesis 只能降权或排除 |
| 策略中心与 Dashboard 策略卡重复 | Dashboard 只展示摘要（1 行），策略中心展示完整详情 |
| Playbook 匹配逻辑过早前端化 | 匹配规则放后端，前端只展示匹配结果 |
| 多 Agent 并发改同一文件 | 按页面/adapter/backend endpoint 拆任务，避免同文件并发 |

## 10. 文档同步

长期记录已维护到 Obsidian：

```text
/home/zxx/wiki/Finance-Agent-Knowledge-Vault/02-项目/金融分析系统/24-系统架构与前后端对接升级计划.md
```

repo 当前状态快照：

```text
docs/frontend/current-frontend-state.md
```

后续如果 P0/P1 阶段完成，应同步更新：

- Obsidian `02-项目/金融分析系统/04-开发路线图.md`
- Obsidian `02-项目/金融分析系统/09-版本记录.md`
- repo `docs/frontend/page-data-map.md`
- repo `docs/frontend/api-contract.md`
