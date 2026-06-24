# Tool Registry

This document lists public, repository-local tool categories used by `finance-agent`.
It intentionally excludes private cloud document publishing, local operator workbench,
browser profile, webhook, chat, and personal knowledge-base workflows.

## Categories

```text
data.*      — data collection
parse.*     — raw-to-structured parsing
compute.*   — deterministic feature computation
agent.*     — read-only analysis
report.*    — report rendering
code.*      — development verification
file.*      — local artifact file handling
```

## data.*

### data.macro.snapshot

- Description: collect and normalize macro indicators.
- Inputs: date, indicator list.
- Outputs: macro snapshot with values, changes, status, and source refs.
- Implementation: `apps/collectors/fred/`, `apps/collectors/fed/`, `apps/collectors/treasury/`, `apps/features/macro/`.

### data.cme.download

- Description: download CME Daily Bulletin PDFs.
- Inputs: report date and bulletin section.
- Outputs: archived raw PDF metadata with checksum and source refs.
- Implementation: `apps/collectors/cme/downloader.py`.

### data.jin10.fetch

- Description: collect Jin10 calendar, flash, quotes, K-line, and article metadata where configured.
- Inputs: source type, date range, optional article id.
- Outputs: raw and parsed Jin10 payloads.
- Implementation: `apps/collectors/jin10/` and `apps/collectors/news/`.

### data.news.collect

- Description: collect public news and official event sources.
- Inputs: source key and date range.
- Outputs: normalized news items and source refs.
- Implementation: `apps/collectors/news/`.

## parse.*

### parse.cme.pdf

- Description: parse CME bulletin PDFs into option rows and parse warnings.
- Inputs: archived PDF path.
- Outputs: structured option tables.
- Implementation: `apps/parsers/cme/`.

### parse.news.item

- Description: normalize collected news or article payloads.
- Inputs: raw payload path or payload object.
- Outputs: structured event or article records.
- Implementation: `apps/parsers/news/`.

## compute.*

### compute.options.gamma

- Description: compute Black-76 Gamma, GEX, option walls, and fallback proxy metrics.
- Inputs: option rows, futures price, rate, volatility fields.
- Outputs: options feature snapshot.
- Implementation: `apps/features/options/`.

### compute.macro.regime

- Description: derive macro liquidity and market regime features.
- Inputs: macro time series and latest indicators.
- Outputs: macro feature snapshot.
- Implementation: `apps/features/macro/` and `apps/analysis/macro/`.

## agent.*

### agent.macro.liquidity

- Description: read-only macro liquidity analysis.
- Inputs: analysis snapshot.
- Outputs: `AgentOutput`.
- Implementation: `apps/analysis/agents/macro_liquidity.py`.

### agent.cme.options

- Description: read-only CME options structure analysis.
- Inputs: options snapshot.
- Outputs: `AgentOutput`.
- Implementation: `apps/analysis/agents/cme_options.py`.

### agent.synthesis

- Description: combine upstream analysis outputs into a final read-only synthesis.
- Inputs: upstream `AgentOutput` list.
- Outputs: synthesis `AgentOutput`.
- Implementation: `apps/analysis/agents/synthesis.py`.

### agent.fact.review

- Description: rule-based fact review.
- Inputs: report or analysis claims with source refs.
- Outputs: supported, partial, unsupported, or contradicted claim status.
- Implementation: `apps/analysis/agents/fact_review.py`.

## report.*

### report.generate.markdown

- Description: render Markdown reports from snapshots, agent outputs, and source refs.
- Outputs: local Markdown artifacts.
- Implementation: `apps/renderer/`.

### report.generate.json

- Description: render structured JSON artifacts for API and frontend use.
- Outputs: local JSON artifacts.
- Implementation: `apps/renderer/` and `apps/output/`.

### report.trace

- Description: generate report lineage and source-trace metadata.
- Outputs: trace metadata bound to run and snapshot ids.
- Reference: `docs/TRACE_SCHEMA.md`.

## code.*

### code.verify.python

- Command: `uv run ruff check .`
- Command: `uv run --extra dev pytest -q`
- Use after Python or contract changes.

### code.verify.frontend

- Command: `cd apps/frontend-web && npm run build`
- Command: `cd apps/frontend-web && npm run typecheck`
- Use after frontend changes.

## file.*

### file.archive.raw

- Description: write source payloads to `storage/raw/`.
- Rule: raw data is append-only during normal runs.

### file.archive.parsed

- Description: write normalized payloads to `storage/parsed/`.
- Rule: parsed artifacts should link back to raw source refs.

### file.write.output

- Description: write reports and derived artifacts to `storage/outputs/`.
- Rule: do not overwrite historical report artifacts.

## Safety Rules

- Do not commit `.env`, keys, tokens, cookies, certificates, private browser profiles, local runtime data, or generated reports.
- Do not publish internal cloud document URLs, Bitable app/table ids, webhook URLs, chat ids, or personal workspace paths.
- External data source usage must follow the corresponding provider terms.
