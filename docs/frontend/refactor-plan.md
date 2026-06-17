# Frontend Refactor Plan

- Project: finance-agent
- Date: 2026-05-24
- Scope: `apps/frontend-web/` frontend refactor planning only
- Status: FE-1 contract baseline
- Source of truth: AGENTS.md + Obsidian `20-前端重构与前后端契约规划.md` + live repo API/frontend structure + `docs/frontend/finanalytics-pro-design-system/FinAnalytics_Preview.html`

## 1. Purpose

This document defines the implementation boundary for the next frontend refactor of `apps/frontend-web/`.

This is not only a backend contract cleanup and not only a page feature migration. The target is a dual refactor:

1. architecture correctness: stable `types / adapters / hooks / mocks / API` contracts;
2. visual restoration: pages should match the latest FinAnalytics Pro dark financial-terminal design closely enough in layout, density, card treatment, tables, badges, right panel, and status bar.

If the architecture is clean but the page still looks like the old placeholder UI, the batch is not accepted. If the page looks close to the design but uses hardcoded business conclusions or drops `sourceTrace / snapshot / artifact` context, the batch is not accepted.

The goal is not to redesign every page at once. The goal is to make frontend/backend reconnection predictable while keeping visual migration anchored to the copied FinAnalytics Pro design source by fixing:

- which backend APIs each page consumes;
- how raw API responses are normalized into frontend ViewModels;
- how unavailable/partial/error states are displayed;
- how `source_refs`, `trade_date`, `run_id`, and report metadata flow to the UI;
- how Codex tasks are split and accepted without scope drift.

## 1.1 Design source

The FinAnalytics Pro design reference has been copied into:

```text
docs/frontend/finanalytics-pro-design-system/
```

Primary reference order:

1. `FinAnalytics_Preview.html` — latest all-in-one preview and current visual source of truth.
2. `ui_kit/ui_kit.css` and `ui_kit/*.jsx` — reusable shell, primitives, status bar, right panel, and page examples.
3. `knowledge-base.html` — dedicated Knowledge Base workstation reference with gold-accent graph/list/ops layout.
4. `reference/*.tsx` — selected page/view references.
5. `screenshots/` and `uploads/01_*.png` through `uploads/09_*.png` — visual-density checks for each page.
6. `README.md` and `SKILL.md` — design intent, density, typography, and component behavior.

If `FinAnalytics_Preview.html` disagrees with older extracted CSS such as `colors_and_type.css`, use `FinAnalytics_Preview.html` first and record the mismatch in the design-system mapping notes. `knowledge-base.html` is page-specific; do not promote its gold accent or graph layout to the global design system without explicit approval.

## 2. Current target

The only active frontend target is:

```text
apps/frontend-web/src/
```

Legacy `apps/frontend/` Next.js and `apps/frontend-web/dashboard.html` have been removed. Do not recreate them for new pages, API integration, or visual work unless explicitly requested for a compatibility repair.

The frontend is a read-only financial research workstation. It displays backend artifacts and structured analysis results. It does not calculate strategy, mutate source data, or reinterpret raw market data.

## 3. Architectural boundary

### Backend owns

- data collection and archiving;
- raw / parsed / features / outputs layering;
- macro, CME options, market odds, Jin10, technical and risk feature generation;
- analysis outputs and report artifacts;
- strategy card generation;
- `snapshot_id`, `input_snapshot_ids`, `source_refs`, `trade_date`, `run_id`;
- unavailable/partial status at source or module level.

### Frontend owns

- shell layout, routing, page composition;
- display density and Chinese copy;
- loading / empty / error / unavailable states;
- date, report family, and run selection controls;
- source trace display;
- report reading UI;
- adapter-level compatibility for stable display.

### Adapter layer owns

- API call paths;
- raw API response validation and safe defaulting;
- Raw API -> ViewModel normalization;
- status normalization: `available | partial | unavailable | error`;
- source metadata propagation;
- mock fallback only when explicitly allowed.

## 4. Non-goals

Do not do these in the refactor unless a later task explicitly allows it:

- do not change backend analysis logic;
- do not change collectors, parsers, features, agents, renderers, worker runner, migrations, or storage layout;
- do not let frontend calculate trading bias, strategy, walls, gamma, macro regime, or risk conclusions;
- do not introduce a second frontend target;
- do not add MUI/Emotion;
- do not rewrite all pages in one task;
- do not hardcode business data or metric order inside display components;
- do not hide unavailable data as normal content.

## 5. Target frontend layering

```text
apps/frontend-web/src/
  pages/                  route-level page composition
  components/
    shell/                AppShell/AppSidebar/AppHeader/ContextRightPanel
    shared/               reusable display primitives
    dashboard/            dashboard-specific panels
    data-ingestion/       ingestion-specific panels
    market-monitor/       market monitor panels
    cme-options/          CME options panels
    reports/              reports reader panels
  adapters/               API calls + Raw API -> ViewModel normalization
  hooks/                  page-level async state wrappers
  types/                  Raw API and ViewModel contracts
  lib/                    formatting, dates, status/source utilities
  mocks/                  explicit development fallback only
```

Existing files do not need to be moved immediately. This is the target boundary for incremental tasks.

## 6. Refactor phases

### FE-1: Contract baseline

Files:

- `docs/frontend/refactor-plan.md`
- `docs/frontend/api-contract.md`
- `docs/frontend/page-data-map.md`
- `docs/frontend/viewmodel-spec.md`
- `hermes/prompts/refactor-01-contract-baseline.md`

Rules:

- documentation only;
- no code changes;
- no Codex dispatch required;
- no backend changes.

Acceptance:

- every P0/P1 page has a data map;
- every active API family has status/source handling notes;
- ViewModel primitives are defined;
- next Codex task package has allowed/forbidden scope.

### Task P0-09 / FE-1.5: FinAnalytics Pro design system mapping

This batch must run after P0-08 first-batch smoke closeout and before broad page visual migration work.

Goal:

Extract and implement the shared visual foundation from `docs/frontend/finanalytics-pro-design-system/FinAnalytics_Preview.html` so that later pages migrate into the latest FinAnalytics Pro dark financial-terminal style instead of preserving old placeholder visuals. Do not copy the HTML into React.

Required extraction:

- color tokens;
- app/background surfaces;
- border colors;
- card styles;
- typography scale and numeric typography;
- spacing, radius, and density;
- badge/status pill styles;
- tab styles;
- table styles;
- right panel styles;
- bottom status bar styles.

Required shell/layout review:

- confirm the existing `AppShell / AppSidebar / AppHeader / ContextRightPanel / DataStatusBar` can carry the new design;
- do not rewrite `AppShell`, `AppSidebar`, or `AppHeader` unless an approved task explicitly allows it;
- preserve the three-pane workstation model: left navigation, central content, right context panel, bottom status bar;
- use `knowledge-base.html` only for the Knowledge Base page shape: list/detail/graph/ops density, not as a global theme replacement.

Shared UI components to add or align:

- `PageHeader`;
- `FAIcon`;
- `FACard`;
- `FAStatusPill`;
- `FAMetricCard`;
- `FASectionHeader`;
- `FAFilterBar`;
- `FATabBar`;
- `FAConvictionBar`;
- `FAEmptyState`;
- `FAWarningBanner`;
- `FAPipelineStepper`;
- `FARuntimeLog`;
- `MetricCard`;
- `StatusBadge`;
- `DataStatusBadge`;
- `SourceTraceBadge`;
- `ConvictionBar`;
- `SectionCard`;
- `FilterBar`;
- `RightRailPanel`;
- `EmptyState`;
- `WarningBanner`;
- `MiniSparkline`.

Required document output:

- update `docs/frontend/design-system.md` with exact token mapping from the HTML design source to project CSS variables/Tailwind classes;
- update or extend `docs/frontend/component-map.md` with HTML/class/style to current-component mapping;
- keep the detailed development split in `docs/frontend/p0-visual-migration-task-plan.md`;
- explicitly list which styles reuse existing components, which require new shared components, and which are intentionally not restored 1:1.

Acceptance:

- no AppShell rewrite;
- no second design system;
- all pages share the same card, badge, table, tab, status, and panel styles;
- new page work must visually approach `FinAnalytics_Preview.html`, not the old placeholder style;
- Knowledge Base may additionally reference `knowledge-base.html` for its dedicated three/four-column workbench layout;
- no Babel / UMD React / unpkg CDN code from the HTML is copied into the app;
- `cd apps/frontend-web && npm run typecheck && npm run build` passes for code changes;
- if the batch is docs-only, record why build was not required.

### FE-2: Shared foundation

Scope:

- common status/source types;
- `SourceTrace`, `StatusBadge`, `EmptyState`, `ErrorState`, `LoadingSkeleton`, `DataStatusBar`;
- format/date/source utilities;
- shell-only polish if required and already approved by Task P0-09 mapping.

No page business rewrite yet.

### FE-3: Dashboard reconnect

Dashboard should answer first: what is the current market state?

Reconnect through `DashboardViewModel`, not page-local raw API parsing.

### FE-4: Data Ingestion reconnect

Display data-source and pipeline health. No analysis.

### FE-5: Market Monitor reconnect

Display live/near-live indicators and macro liquidity metrics. Individual indicators may be unavailable without breaking the page.

### FE-6: CME Options reconnect

Display options snapshot, walls, gamma zero, key levels, data quality, report entry. Do not calculate options analytics in frontend.

### FE-7: Reports Center reconnect

Unify final report, CME visual report, Jin10 bundle, report index/date/run selection.

### FE-8: Agent Tasks and final closeout

Task observability pages and final typecheck/build/API/route smoke.

## 7. Required state handling

Every page-level ViewModel must represent:

- `available`: enough data to render main content;
- `partial`: page can render, but one or more modules are unavailable;
- `unavailable`: backend has no persisted artifact/data for the requested selection;
- `error`: request or normalization failed.

Structured read APIs should prefer HTTP 200 with status `unavailable` when the route exists but data is absent. Passthrough raw snapshot endpoints may still return 404 for a specific missing file.

## 8. Source trace rule

Any module showing analysis, report conclusions, strategy, key levels, market state, risk, or data-source status must expose source context when available:

- endpoint path;
- `source_ref`;
- artifact path;
- `snapshot_id`;
- `input_snapshot_ids`;
- `trade_date`;
- `run_id`.

The UI may display this compactly, but the data should not be dropped by adapters.

## 9. Codex task discipline

Do not dispatch a broad “refactor frontend” task.

Each Codex prompt must state:

- task goal;
- allowed files;
- forbidden files;
- input files;
- exact steps;
- acceptance checklist;
- validation commands;
- report format.

For this user's workflow:

- prompt files are written to `hermes/prompts/`;
- dispatch uses `scripts/dev-dispatch.sh frontend <task-file>`;
- dispatch only counts after the visible right-side Codex pane shows `Working`;
- if Codex generates a plan, Hermes/main controller must confirm it before approval;
- acceptance requires real diff/log/test/output evidence, not only pasted text.

## 9.1 Hard restrictions

1. Do not rewrite `AppShell / AppSidebar / AppHeader` unless the task explicitly allows it.
2. Do not delete existing pages or routes.
3. Do not calculate financial analysis in React components.
4. Do not hardcode business conclusions to restore visual fidelity.
5. Do not present mock state as real `LIVE`.
6. Do not store API keys in frontend code or plaintext frontend state.
7. Do not migrate all pages in one task.
8. Each batch must be independently reviewable and accepted.
9. Each code batch must run `typecheck`, `lint` when available, and `build`.
10. Visual work must compare against `FinAnalytics_Preview.html`, not freeform redesign.

## 9.2 UI restoration acceptance

Every page migration has two acceptance dimensions:

1. Architecture: `types / adapter / hook / mock / API` boundaries are clear and source trace is preserved.
2. Visual fidelity: layout, card density, tables, badges, right panel, status bar, and dark terminal style match the FinAnalytics Pro reference.

Global UI acceptance:

- Pages must use the FinAnalytics Pro dark financial-terminal style.
- Left Sidebar, top Header, bottom status bar, and right Context Panel remain the product layout baseline.
- Wide screens must stay close to the three-column design: left navigation, central main content, right context panel.
- Cards, tables, badges, tabs, buttons, and status bars must be shared components or shared classes, not page-local one-off styling.
- Mock data should be dense and close to the design reference, so visual density can be validated.
- Pages must not show large blank areas, default white backgrounds, or browser-native controls.
- After each page, compare with `FinAnalytics_Preview.html` for layout, information hierarchy, status color, card density, right panel, and table readability.
- Knowledge Base should additionally compare against `knowledge-base.html` for list/detail/graph/ops structure.

Expected visual difficulty by page:

| Page | Expected fit after current plan | Main visual gap |
|---|---:|---|
| Reports | 85% | Card style and detail page visual density |
| Data Ingestion | 85% | Table density and right-side blocker panel |
| Agent Tasks | 80% | Terminal-style logs and progress cards |
| Dashboard | 70% | High information density; needs design skeleton first |
| Market Monitor | 75% | Charts, heatmap, diagnostic panel components |
| CME Options | 75% | GEX chart, level track, right-side script panel |
| Event Flow | 70% | Causal chain component needs dedicated design |
| Knowledge Base | 75% | Three-column knowledge workstation layout from `knowledge-base.html` |
| Settings | 85% | Card forms are easier to restore |

## 10. Validation bundle

Minimum validation after frontend code tasks:

```bash
cd apps/frontend-web && npm run typecheck
cd apps/frontend-web && npm run build
```

When API contracts or route assumptions are touched:

```bash
uv run pytest tests/api/ -q
```

Recommended live smoke after startup:

- `GET /health`
- `GET /api/dashboard/summary`
- `GET /api/reports/index`
- `GET /api/data-status/summary`
- `GET /api/options/snapshot`
- `GET /api/jin10/report-bundle/latest`

Recommended route smoke:

- `/`
- `/dashboard`
- `/data-ingestion`
- `/market-monitor`
- `/cme-options`
- `/reports`

## 11. Immediate next task

Proceed with Task P0-09 before expanding page visual migration batches.

P0-09 should start from the copied FinAnalytics Pro design source and produce a design-system mapping plus shared visual primitives. Page tasks P0-10 to P0-15 should then use those primitives instead of page-specific redesign.
