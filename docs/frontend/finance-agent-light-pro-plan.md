# Finance Agent Light Pro

> Created: 2026-06-29
> Scope: `apps/frontend-web/src`
> Status: active frontend visual direction

## Product Direction

Finance Agent should read as an internal institutional gold macro research terminal, not a generic admin dashboard and not a dark trading skin.

The target visual language is:

- light institutional research system
- white surfaces on a blue-gray background
- generous reading rhythm
- professional tables and restrained charts
- fewer cards, larger work areas
- one main workspace plus one inspector/evidence rail per page
- visible source trace, data quality, partial, fallback, and unavailable states

## Theme

Name: `Finance Agent Light Pro`

Core palette:

```text
Background      #F6F8FB
Card            #FFFFFF
Subtle area     #F9FAFB
Border          #E5E7EB
Primary text    #0F172A
Secondary text  #64748B
Muted text      #94A3B8
Primary blue    #2563EB
Gold accent     #B7791F
Up green        #059669
Down red        #DC2626
Warning orange  #D97706
```

Avoid full-page dark blue, glow borders, heavy gradients, decorative card mosaics, and admin-template clutter.

## Product Areas

```text
Research
  /dashboard
  /strategy

Market
  /market-monitor
  /cme-options

Intelligence
  /event-flow
  /feishu-monitor

Library
  /reports
  /reports/:id
  /knowledge-base
  /knowledge/:id

Operations
  /data-ingestion
  /scheduler
  /review-center
  /settings
  /settings/audit
```

## Page Rules

Every page has at most four layers:

```text
L1: page title / current state
L2: core conclusion / current working object
L3: main workspace
L4: evidence / details / operations
```

Each page should have:

- one clear purpose
- one main narrative
- one main visual/workspace
- at most one right-side rail
- a small number of high-signal metrics

## Shared Components

Phase 1 establishes:

- `PageSummary`
- `SummaryStrip`
- `WorkspaceLayout`
- `InspectorRail`
- `EvidenceRail`
- `StatusChip`
- `ReportReader`
- `DataModeBanner`

## Execution Order

Phase 1:

1. Light Pro tokens and shell.
2. Shared layout primitives.
3. Dashboard -> Research Command.

Phase 2:

1. Market Monitor -> Market Workspace.
2. Report Detail -> Report Reader.

Phase 3:

1. Data Ingestion -> Data Operations.
2. Event Flow -> Intelligence Hub.
3. CME Options -> Options Desk.

Phase 4:

1. Strategy -> Strategy Memo.
2. Knowledge Base -> Knowledge Registry.
3. Scheduler -> Run Console.
4. Review Center and Settings cleanup.
