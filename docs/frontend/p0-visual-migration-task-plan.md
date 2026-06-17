# P0 Visual Migration Task Plan

- Project: finance-agent
- Target frontend: `apps/frontend-web`
- Design source: `docs/frontend/finanalytics-pro-design-system/FinAnalytics_Preview.html`
- Knowledge Base reference: `docs/frontend/finanalytics-pro-design-system/knowledge-base.html`
- Status: **P0-09 ~ P0-15 全部完成** (2026-05-28 visual refinement pass closed)

## 1. Position In The Current P0 Chain

P0-00 to P0-08 established the data and traceability foundation: frontend API contract mapping, shared SourceTrace/Snapshot/Artifact concepts, Reports Detail, Agent Tasks, and Data Ingestion state semantics.

P0-09 must sit between that data foundation and the next page-visual migration work:

```text
P0-08 first-batch smoke closeout
-> P0-09 FinAnalytics Pro design system mapping
-> P0-10 Reports visual alignment
-> P0-11 Agent Tasks visual alignment
-> P0-12 Data Ingestion visual alignment
-> P0-13 Dashboard new design migration
-> P0-14 Market Monitor new design migration
-> P0-15 CME Options new design migration
```

Do not skip P0-09. If Dashboard / Market / CME starts before the visual primitives are mapped, those pages will likely be data-correct but visually inconsistent with the latest design.

## 2. Global Execution Principles

1. Do not copy `FinAnalytics_Preview.html` directly into React.
2. Do not rewrite `AppShell / AppSidebar / AppHeader`.
3. Do not introduce unpkg / Babel / UMD React / CDN runtime dependencies.
4. Do not hardcode mock business conclusions into production pages.
5. Preserve existing `types / adapters / hooks / sourceTrace / snapshot / artifact` contracts.
6. Shared components only render props; they do not fetch data or compute financial analysis.
7. Each task must pass `cd apps/frontend-web && npm run typecheck && npm run build`.
8. Each task must be independently reviewable and should not modify unrelated pages.

## 3. Task Breakdown

### Task P0-09: FinAnalytics Pro Design System Mapping

Description:
Extract tokens, layout rules, and reusable UI patterns from `FinAnalytics_Preview.html`, then map them into `apps/frontend-web` CSS variables and shared display components.

Acceptance criteria:

- [ ] FinAnalytics surface, border, foreground, brand, semantic, chart, typography, spacing, radius, and shell-width tokens are mapped.
- [ ] Existing CSS variables stay compatible; no second design system is introduced.
- [ ] Shared components exist or are aligned for card, status pill, metric card, section header, filter bar, tab bar, conviction bar, empty state, warning banner, pipeline stepper, runtime log, and source trace badge.
- [ ] `FinAnalytics 设计系统映射报告` is recorded in `docs/frontend/design-system.md` and `docs/frontend/component-map.md`.
- [ ] `npm run typecheck` and `npm run build` pass.

Dependencies:

- P0-08 complete or stable enough that Reports / Agent Tasks / Data Ingestion contracts are not moving.

Files likely touched:

- `apps/frontend-web/src/index.css`
- `apps/frontend-web/src/styles/finanalytics-tokens.css`
- `apps/frontend-web/src/components/shared/*.tsx`
- `docs/frontend/design-system.md`
- `docs/frontend/component-map.md`
- `hermes/prompts/p0-09-finanalytics-design-system-mapping.md`

### Task P0-10: Reports Visual Alignment

Description:
Apply P0-09 shared visual primitives to Reports list and Report Detail while preserving current route-based detail pages and report artifact/source contracts.

Acceptance criteria:

- [ ] Reports cards visually match the FinAnalytics dense card style.
- [ ] Report Detail keeps the existing route model and does not revert to HTML overlay behavior.
- [ ] SourceTrace, artifact refs, report metadata, and unavailable states remain visible.
- [ ] No direct page-level fetch is introduced.
- [ ] `npm run typecheck` and `npm run build` pass.

Dependencies:

- P0-09.

Files likely touched:

- `apps/frontend-web/src/pages/ReportsPage.tsx`
- `apps/frontend-web/src/pages/ReportDetailPage.tsx`
- `apps/frontend-web/src/components/reports/*.tsx`
- Reports shared visual components only as needed.

### Task P0-11: Agent Tasks Visual Alignment

Description:
Apply P0-09 shared visual primitives to Agent Tasks run list, step timeline, artifact refs, and runtime logs.

Acceptance criteria:

- [ ] Run cards and task rows use shared card/status/progress components.
- [ ] Pipeline visual follows the design's research flow: raw data, parsed data, features, agent reasoning, report output, knowledge deposition.
- [ ] Runtime logs use a terminal-style `FARuntimeLog` or equivalent component.
- [ ] Existing `/api/runs*` and fallback task contracts remain untouched.
- [ ] `npm run typecheck` and `npm run build` pass.

Dependencies:

- P0-09.

Files likely touched:

- `apps/frontend-web/src/pages/AgentTasksPage.tsx`
- `apps/frontend-web/src/components/shared/FARuntimeLog.tsx`
- `apps/frontend-web/src/components/shared/FAPipelineStepper.tsx`

### Task P0-12: Data Ingestion Visual Alignment

Description:
Apply P0-09 shared visual primitives to Data Ingestion status, source cards, blocker/summary panels, and table density.

Acceptance criteria:

- [ ] Data source cards use shared status pill and source trace patterns.
- [ ] Data status summary and blocker panels are dense and visually aligned with the design.
- [ ] unavailable / partial / error states remain explicit.
- [ ] No data-source business logic is moved into React components.
- [ ] `npm run typecheck` and `npm run build` pass.

Dependencies:

- P0-09.

Files likely touched:

- `apps/frontend-web/src/pages/DataIngestionPage.tsx`
- `apps/frontend-web/src/components/data-ingestion/*.tsx`
- shared visual components only as needed.

### Task P0-13: Dashboard New Design Migration

Description:
Rebuild Dashboard visual composition using P0-09 primitives while keeping Dashboard as an overview page, not a replacement for Market / CME / Reports detail pages.

Acceptance criteria:

- [ ] Dashboard uses dense FinAnalytics dashboard layout for daily judgment, KPI strip, market snapshot, CME summary, latest reports, and data health.
- [ ] Dashboard does not compute strategy, price levels, gamma, or macro regime in frontend.
- [ ] Mock/API data remains adapter-driven and source trace remains visible.
- [ ] Large blank placeholder areas are removed.
- [ ] `npm run typecheck` and `npm run build` pass.

Dependencies:

- P0-09.
- Prefer after P0-10 to P0-12 validate shared visual primitives on simpler pages.

Files likely touched:

- `apps/frontend-web/src/pages/DashboardPage.tsx`
- `apps/frontend-web/src/components/dashboard/*.tsx`
- shared visual components only as needed.

### Task P0-14: Market Monitor New Design Migration

Description:
Apply FinAnalytics market-monitor layout patterns: price cards, diagnostic panels, table/heatmap-style density, and right-panel source context.

Acceptance criteria:

- [ ] Market price cards and macro panels use shared visual primitives.
- [ ] Heatmap/table-style sections follow FinAnalytics density and numeric typography.
- [ ] Missing indicators remain `unavailable`, not hidden or fabricated.
- [ ] No market calculations are added to frontend components.
- [ ] `npm run typecheck` and `npm run build` pass.

Dependencies:

- P0-09.
- Prefer after P0-13 if Dashboard reuses market-summary components.

Files likely touched:

- `apps/frontend-web/src/pages/MarketMonitorPage.tsx`
- `apps/frontend-web/src/components/market-monitor/*.tsx`
- shared chart/table primitives if introduced.

### Task P0-15: CME Options New Design Migration

Description:
Apply FinAnalytics CME options layout patterns: wall table, gamma/key-level cards, GEX/level-track visual primitives, source trace, and report entry.

Acceptance criteria:

- [ ] Options summary, wall table, gamma zero, key level map, and source trace use shared visual primitives.
- [ ] Frontend does not calculate GEX, option walls, or trading conclusions.
- [ ] FINAL/PRELIM/unavailable states remain visually explicit.
- [ ] Existing CME adapter/hook contracts remain stable.
- [ ] `npm run typecheck` and `npm run build` pass.

Dependencies:

- P0-09.
- Prefer after P0-14 if chart/table primitives are shared.

Files likely touched:

- `apps/frontend-web/src/pages/CMEOptionsPage.tsx`
- `apps/frontend-web/src/components/cme-options/*.tsx`
- shared chart/table primitives if introduced.

## 4. Later Tasks

Event Flow, Knowledge Base, and Settings should follow after P0-15 unless explicitly reprioritized.

Knowledge Base has a dedicated reference:

```text
docs/frontend/finanalytics-pro-design-system/knowledge-base.html
```

Use it for Knowledge Base layout only: knowledge item list, detail workspace, graph panel, and ops panel. Do not promote its gold-accent theme as the global FinAnalytics theme.

## 5. Checkpoints

Checkpoint after P0-09:

- [ ] Shared visual primitives are stable enough for page migration.
- [ ] Typecheck/build pass.
- [ ] Design-system mapping doc is clear enough for another Codex session.

Checkpoint after P0-10 to P0-12:

- [ ] Reports / Agent Tasks / Data Ingestion preserve current data contracts.
- [ ] Shared components are reusable without page-local visual forks.
- [ ] Visual density is close to the design reference.

Checkpoint after P0-13 to P0-15:

- [ ] Dashboard / Market / CME follow one design language.
- [ ] No frontend financial computation has been introduced.
- [ ] Route smoke and frontend build pass.

## 6. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Copying HTML directly | Breaks React architecture and imports CDN/UMD runtime | P0-09 only extracts tokens and components |
| Rewriting Shell | Risks route/layout regressions | Only token/class alignment unless a task explicitly allows more |
| Page-local styling forks | Future pages drift visually | Require shared components/classes first |
| Mock conclusions leak into production UI | Misrepresents analysis state | Mock data stays in mocks; components render props only |
| Tailwind version mismatch | Invalid CSS if assuming Tailwind 4 `@theme` | Current project uses Tailwind 3.4; use CSS variables and utilities |

## 7. 完成记录

P0-09 ~ P0-15 已于 2026-05-28 全部完成，visual refinement pass 收口。

### 各任务最终状态

| Task | 状态 | 关键变更 |
|---|---|---|
| P0-09 Design System | ✅ 完成 | CSS tokens、shared components (FACard/FAStatusPill/FAMetricCard/FAFilterBar/FATabBar/FAEmptyState/FAWarningBanner/FASourceTraceBadge) 全部就位 |
| P0-10 Reports | ✅ 完成 | 卡片加类型摘要/标签、筛选侧边栏 10 类型/资产/状态/数据源/日期范围、按 (type, date) 去重 |
| P0-11 Agent Tasks | ✅ 完成 | 任务流程时间线、结果面板、统计指标 |
| P0-12 Data Ingestion | ✅ 完成 | 数据源注册表、状态卡、最近活动 |
| P0-13 Dashboard | ✅ 完成 | 综合判断卡、价格卡、持仓分析、置信度趋势图、收紧间距 |
| P0-14 Market Monitor | ✅ 完成 | 因子卡片、联动图+FactorPanel 右侧、资产表+热力图 |
| P0-15 CME Options | ✅ 完成 | 紧凑统计卡、墙位分析、支撑阻力、IV Skew、墙位明细可展开 |
| Event Flow | ✅ 完成 | 事件时间线、传导链、情绪指标、风险雷达 |
| Knowledge Base | ✅ 完成 | 知识条目列表、详情、运维面板 |

### 2026-05-28 Visual Refinement Pass

本轮收口的额外视觉调整：

- **CME Options**: 移除 PRELIM 横幅/日期 Tab、墙位明细默认折叠、补回 IV Skew / Tail Risk、移除 OptionsMarketReadout（有用部分合入 GammaZeroCard）
- **Dashboard**: 收紧 padding/gap、去除判断卡上方空白
- **Market Monitor**: FactorPanel 从图表下方提取到右侧 218px 列
- **Reports**: 卡片含 TYPE_DESCRIPTIONS 摘要+标签、ReportsRail 完整筛选体系、(type, date) 去重
- **Event Flow**: 移除 PageHero
- **Knowledge Base**: 移除 Header/Metrics/Spotlight 顶部区域
- **全局**: `.app-content` 移除 radial gradient overlay，统一 `var(--bg-app)` 背景
