# Institutional Finance Research Terminal Frontend Plan

> Created: 2026-06-28
> Scope: `apps/frontend-web/src`
> Status: execution plan; no implementation changes in this document

## 1. Product Positioning

The frontend target is an **Institutional Finance Research Terminal**:

```text
Bloomberg / TradingView market information density
+ Grafana data source and runtime observability panels
+ Superset research exploration and filter structure
+ Tremor / shadcn modern React + Tailwind component quality
```

This is not a generic admin dashboard and not a decorative SaaS analytics page. The UI should feel like:

- a market research workstation for XAUUSD / macro / CME options;
- a data observability console for freshness, lineage, source health, runs, and artifacts;
- a report workbench for institutional reading, evidence review, and source trace.

## 2. Hard Boundaries

- Target only `apps/frontend-web/src` for implementation.
- Keep the current Vite + React + TypeScript + Tailwind frontend as the only active frontend entry.
- Do not modify backend logic as part of visual refactors.
- Do not calculate strategy, macro, options, or event conclusions in the frontend.
- Do not hide `mock`, `fallback`, `partial`, `unavailable`, stale, or error states.
- Preserve current routes and API adapters unless a separate API contract task explicitly changes them.
- Keep current controlled write actions as controlled actions; do not invent local success state.

## 3. Reference Stack

Use the external projects as visual and structural references, not as code to copy wholesale.

| Reference | Role | Use In Finance-Agent | Boundary |
|---|---|---|---|
| `shadcn-ui/ui` | base component system | `Button`, `Card`, `Badge`, `Tabs`, `Table`, `Sheet`, `Dialog`, `Select`, `Tooltip`, `Skeleton`, `Command`, toast | not a complete finance dashboard template |
| `satnaing/shadcn-admin` | Vite + shadcn admin shell | AppShell, Sidebar, global command search, Settings, responsive admin primitives | do not copy route or business structure |
| `tremorlabs/tremor` | analytics components | KPI cards, chart cards, tabs, tables, dashboard blocks | use density and component grain, not a one-note SaaS dashboard |
| `TailAdmin/free-react-tailwind-admin-dashboard` | React + Tailwind dashboard layout | dashboard page rhythm, dark mode, metric/chart panels | use visual hierarchy only |
| `tabler/tabler` | mature admin visual hierarchy | tables, status badges, settings, library/list density | not a React/Tailwind migration target |
| `themesberg/flowbite-admin-dashboard` | CRUD/settings/drawer patterns | Data Ingestion, Settings, Review Center, empty/error states | do not switch component stack to Flowbite |
| `coreui/coreui-free-react-admin-template` | stable enterprise layout | responsive layout and management-page stability | not the primary visual direction |
| Grafana | observability model | scheduler, data source status, runtime logs, panels, rows, source state | not a second dashboard engine |
| Dify / n8n / Flowise | run/DAG console | DAG canvas, node inspector, runtime log, workflow state | not a new worker/scheduler architecture |

## 4. Component Layering

Keep shadcn-style primitives and finance-agent domain components separate:

```text
components/ui/
  button.tsx
  card.tsx
  badge.tsx
  tabs.tsx
  table.tsx
  sheet.tsx
  dialog.tsx
  dropdown-menu.tsx
  select.tsx
  tooltip.tsx
  skeleton.tsx
  command.tsx

components/shared/
  FACard.tsx
  FAPageScaffold.tsx
  PageHero.tsx
  DataModeBanner.tsx
  FinanceMetricCard.tsx
  SourceTracePanel.tsx
  EvidenceRail.tsx
  ArtifactRefList.tsx
  RunSnapshotBadge.tsx
  SectionToolbar.tsx

components/layouts/
  CommandCenterLayout.tsx
  MarketWorkstationLayout.tsx
  ResearchLibraryLayout.tsx
  RunConsoleLayout.tsx
  GovernanceLayout.tsx

components/features/
  dashboard/*
  market-monitor/*
  reports/*
  scheduler/*
  settings/*
```

Rules:

- `components/ui` provides generic shadcn-style primitives.
- `components/shared` provides finance-agent domain primitives.
- `components/layouts` owns page templates and major regions.
- `components/features` owns page-specific data rendering.

## 5. Global Visual Baseline

### Color

Use restrained dark financial surfaces:

```text
root background: #070D16 / #0B1220
panel/card:      #111827 / #0F172A
border:          rgba(148, 163, 184, 0.14)
blue:            links, active state, selected state
gold:            XAUUSD, strategy emphasis, warning only
green:           success / live
red:             failure / risk
orange:          partial / fallback
```

Avoid all-card gradients. Large areas should stay quiet; only critical status needs emphasis.

### Typography

Target readable compact density:

```text
page title:   20px / 22px
card title:   13px / 14px
body:         12px / 13px
secondary:    11px
micro label:  10px; avoid repeated 8px / 9px text
```

Use tabular numeric / mono treatment for prices, rates, timestamps, run ids, snapshot ids, and artifact ids.

### Spacing

```text
page gap:              16px
card body padding:     16px
compact card padding:  12px
page horizontal pad:   22px
console pages:         14px is acceptable when canvas density matters
```

Reduce nested scrolling. Prefer one predictable page scroll plus fixed/collapsible console regions where needed.

## 6. Page Templates

### 6.1 Command Center Template

Applies to:

```text
/dashboard
/dashboard/analysis
/strategy
```

Goal: first-screen market judgment, confidence, drivers, risk state, data quality, latest reports.

Target structure:

```text
Market Command Header
XAUUSD Bias / Confidence / Data Mode / Updated / Run / Snapshot

Core KPI Row
XAUUSD / DXY / US10Y / Gamma Zero or Pin Level / Strategy Confidence

Main Thesis + Operations Rail
current judgment / key drivers / invalidation / SourceTrace
data freshness / latest run / latest reports / review needed

Options Mini Panel + Event / News Summary
```

Implementation direction:

| Current | Target |
|---|---|
| `JudgmentBanner` | `CommandCenterHero` |
| `CompactKPICard` | `FinanceMetricCard` |
| `DashboardAnalysisPanel` | `MainThesisPanel` |
| `DashboardRightPanel` | `OperationsRail` |
| `CMEOptionsSummary` | `OptionsMiniPanel` |

Dashboard should keep only five first-screen KPIs. Full details move to `/dashboard/analysis`.

### 6.2 Market Workstation Template

Applies to:

```text
/market-monitor
/cme-options
```

Goal: chart-first market workstation, with right-side regime and source state.

Market Monitor structure:

```text
Market Header
XAUUSD price / change / source / tabs

Price or factor chart 60%-70% + right regime rail
Market Regime / Primary Driver / Confidence / Data Freshness / SourceTrace

Second-layer tabs
Macro Factors / Cross Asset / Calendar
```

CME Options structure:

```text
Options Structure Header
GC / trade date / expiry / data status

Gamma Zero / Pin Level / Top Wall / Intent

GEX or Gamma Chart + Wall Map / Key Strikes

Scenario + Source Trace / Data Quality
```

The frontend only visualizes options results returned by the backend.

### 6.3 Research Library Template

Applies to:

```text
/reports
/reports/:reportId
/knowledge-base
/knowledge/:knowledgeId
```

Goal: institutional research library plus evidence reader.

Reports list structure:

```text
Research Library Header
report count / latest date / asset / data mode

Filter Rail + Featured Latest Report
family / asset / status / date

Report cards / timeline / list / pagination
```

Report detail structure:

```text
Report Header
title / asset / date / run / snapshot / data quality

Report Reader + Evidence Rail
markdown/html/analysis body
source trace / artifacts / inputs / reviews

Top switch
analysis / source / visual
```

Avoid turning report detail into one large card with many equal-weight tabs. Reading and evidence should be visible at the same time on desktop.

### 6.4 Run Console Template

Applies to:

```text
/scheduler
/scheduler/grid
/scheduler/tasks
/agent-tasks/:runId
/review-center
```

Goal: Grafana + Dify-style execution console for runs, logs, source refs, artifacts, and review actions.

Scheduler DAG structure:

```text
Run Console Top Bar
Run Premarket / Preflight / Latest Run / Data Readiness

DAG Canvas + Inspector
collector -> parser -> features -> analysis -> output
node detail / source refs / artifacts

Runtime Log
events / errors / warnings
```

Rules:

- DAG canvas should be the main visual area.
- Inspector stays fixed on the right.
- Runtime log can be collapsible.
- Do not infer DAG truth from frontend-only state.

Run detail structure:

```text
Run Header
status / progress / run_id / snapshot / result

Step Timeline + Runtime Context
source refs / artifact refs / review items / related reports

Logs / Events / Inputs / Outputs
```

### 6.5 Governance Console Template

Applies to:

```text
/settings
/settings/audit
/review-center
```

Goal: settings, audit, and review as a governance center, not a generic form page.

Settings structure:

```text
Governance Header
config source / audit enabled / secrets masked

Settings Tabs + Active Panel
general / datasources / secrets / agents

Recent Audit Events
```

Audit structure:

```text
Audit Event List + Event Detail
diff / actor / reason / request_id / rollback capability if supported
```

## 7. Route To Template Map

| Route | Template | Primary References | First Change |
|---|---|---|---|
| `/dashboard` | Command Center | Tremor + Grafana + Bloomberg density | hero, 5 KPI row, operations rail |
| `/dashboard/analysis` | Research Detail | report reader | full analysis reader |
| `/market-monitor` | Market Workstation | TradingView + Tremor | chart-first layout, regime rail |
| `/cme-options` | Options Workbench | TradingView + analytics dashboard | gamma/wall/scenario two-column layout |
| `/reports` | Research Library | Superset + Tabler + shadcn-admin | filter rail, featured latest report, report grid/list |
| `/reports/:id` | Report Reader | research portal | reader + evidence rail |
| `/event-flow` | Intelligence Board | Jin10 + TradingView + Bloomberg news | event layers, timeline, impact chain |
| `/feishu-monitor` | Message Intake Console | inbox + pipeline intake | raw message list to event/report chain |
| `/scheduler` | Run Console | Grafana + Dify | full-screen DAG, inspector, runtime log |
| `/scheduler/grid` | Ops Overview | Grafana | readiness and run summary panels |
| `/scheduler/tasks` | Run Table | Grafana table | filterable status table and run links |
| `/agent-tasks/:runId` | Run Detail | trace viewer | step timeline + artifacts |
| `/strategy` | Strategy Workspace | research terminal | scenarios, invalidation, evidence |
| `/review-center` | Governance Queue | review workflow | queue, source, status, action clarity |
| `/settings` | Governance Console | shadcn-admin + Flowbite | controlled forms, audit state |
| `/settings/audit` | Audit Viewer | security audit | list/detail diff viewer |

## 8. Execution Plan

### PR-0: Dirty Boundary / Scope Reset

Goal: prevent the accidental scheduler-only edit from becoming the design baseline.

Tasks:

- Inspect current dirty files.
- Decide whether the current `PipelineDagPage.tsx` local change is kept for later Run Console PR or reverted by explicit user request.
- Do not mix frontend design-system baseline with macro/report backend dirty work.

Verification:

- `rtk git status --short`
- clear handoff listing touched files and excluded dirty files.

### PR-1: Design System Baseline

Status: completed locally on 2026-06-28; verified with frontend typecheck/build, target `git diff --check`, and screenshots for `/dashboard`, `/reports`, `/settings`, and mobile `/dashboard`.

Scope:

```text
apps/frontend-web/src/styles/finanalytics-tokens.css
apps/frontend-web/src/index.css
apps/frontend-web/src/components/shared/FACard.tsx
apps/frontend-web/src/components/shared/FAPageScaffold.tsx
apps/frontend-web/src/components/shared/PageHero.tsx
apps/frontend-web/src/components/shared/DataModeBanner.tsx
apps/frontend-web/src/components/shared/FinanceMetricCard.tsx
apps/frontend-web/src/components/shared/RunSnapshotBadge.tsx
apps/frontend-web/src/components/shared/SourceTracePanel.tsx
```

Goals:

- larger readable type scale;
- calmer dark terminal surfaces;
- less gradient/shadow noise;
- consistent card title/body/action density;
- real page scaffold with hero/status/actions/toolbar/body;
- explicit data mode banners for non-live states.

Verification:

```bash
rtk npm run typecheck --prefix apps/frontend-web
rtk npm run build --prefix apps/frontend-web
```

### PR-2: Dashboard + Strategy Command Center

Scope:

```text
apps/frontend-web/src/pages/DashboardPage.tsx
apps/frontend-web/src/pages/DashboardAnalysisPage.tsx
apps/frontend-web/src/pages/StrategyPage.tsx
apps/frontend-web/src/components/dashboard/*
apps/frontend-web/src/components/strategy/*
```

Goals:

- `/dashboard` becomes a true command center;
- keep only five first-screen KPIs;
- move expanded analysis to `/dashboard/analysis`;
- strategy remains backend-driven and evidence-backed.

### PR-3: Market Workstation

Scope:

```text
apps/frontend-web/src/pages/MarketMonitorPage.tsx
apps/frontend-web/src/pages/CMEOptionsPage.tsx
apps/frontend-web/src/components/market-monitor/*
apps/frontend-web/src/components/cme-options/*
```

Goals:

- chart-first market monitor;
- right rail for regime, primary driver, confidence, freshness;
- CME options as gamma/wall/scenario workbench.

### PR-4: Research Library / Report Reader

Scope:

```text
apps/frontend-web/src/pages/ReportsPage.tsx
apps/frontend-web/src/pages/ReportDetailPage.tsx
apps/frontend-web/src/components/reports/*
apps/frontend-web/src/components/knowledge/*
```

Goals:

- reports list becomes a research library;
- detail page becomes report reader + evidence rail;
- SourceTrace, artifacts, inputs, reviews stay visible.

### PR-5: Run Console

Scope:

```text
apps/frontend-web/src/pages/PipelineDagPage.tsx
apps/frontend-web/src/pages/SchedulerCenterPage.tsx
apps/frontend-web/src/pages/TaskScheduleListPage.tsx
apps/frontend-web/src/pages/AgentTaskDetailPage.tsx
apps/frontend-web/src/components/dag/*
apps/frontend-web/src/components/agent-tasks/*
```

Goals:

- scheduler becomes a full-screen run console;
- DAG canvas is primary;
- inspector and runtime log are stable regions;
- run detail shows timeline, context, artifacts, events, inputs, outputs.

### PR-6: Governance Console

Scope:

```text
apps/frontend-web/src/pages/SettingsPage.tsx
apps/frontend-web/src/pages/SettingsAuditPage.tsx
apps/frontend-web/src/pages/ReviewCenterPage.tsx
apps/frontend-web/src/components/settings/*
apps/frontend-web/src/components/review/*
```

Goals:

- settings look like governance, not generic forms;
- audit events use list/detail structure;
- review queue clearly shows source, status, reason, and action.

## 9. Shared Components To Add First

```text
PageHero
DataModeBanner
FinanceMetricCard
SourceTracePanel
EvidenceRail
ArtifactRefList
RunSnapshotBadge
EmptyPanel
SectionToolbar
```

`DataModeBanner` is mandatory for pages that can show fallback, mock, partial, unavailable, or manual-required data.

## 10. Validation Standard

For each implementation PR:

```bash
rtk npm run typecheck --prefix apps/frontend-web
rtk npm run build --prefix apps/frontend-web
```

For visible UI changes:

- run the local frontend;
- check desktop and mobile widths where the page has responsive risk;
- confirm no overlapping text, broken chart canvas, hidden unavailable state, or console/network errors;
- capture route-level browser evidence when a page layout changes.

Completion cannot be claimed from code diff alone.

## 11. Immediate Next Step

Do not start by continuing the isolated scheduler page change.

**PR-1 Design System Baseline** is completed locally as of 2026-06-28:

1. Normalize tokens and global surfaces.
2. Upgrade `FACard` and `FAPageScaffold`.
3. Add the shared finance primitives.
4. Verify the shared baseline with typecheck/build and representative screenshots.

Next, proceed with **PR-2 Dashboard + Strategy Command Center**. Do not continue the isolated scheduler page change until the Run Console PR.
