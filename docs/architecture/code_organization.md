# Code Organization Boundaries

This document records the code-bound boundaries introduced by issue #48. It is
not a product roadmap; current source code and tests remain the final source of
truth.

## Layer Rules

```text
contracts do not import business logic
contracts/domain do not import api
analysis agents do not import api services
api services may import domain/contracts
worker may import api services only through explicit service boundaries
frontend consumes API responses and generated contracts
```

## Contracts

Canonical cross-layer identifiers live under `apps/contracts/`.

- `apps/contracts/gold.py` owns the Gold mainline and transmission identifiers.
- `apps/gold_mainline_contract.py` is a compatibility shim for older imports.
- New backend code should import `apps.contracts.gold`.
- Frontend Gold identifier types are generated from the Python contract into
  `apps/frontend-web/src/generated/gold-contract.ts`.

Generation command:

```bash
rtk uv run python scripts/generate_frontend_contracts.py
```

Check command:

```bash
rtk uv run python scripts/generate_frontend_contracts.py --check
```

## Analysis Agents

Analysis agents own deterministic analysis, quality evaluation, fallback task
construction, and domain reparse behavior.

- Analysis code must not import `apps.api.services.*`.
- API services wrap analysis/domain results for read models and routes.
- `apps/analysis/agents/quality_gate_evaluator.py` owns the quality gate
  evaluator contract.
- `apps/analysis/agents/fallback_executor.py` owns AgentLoop fallback execution.

## API Services

API services should stay as read-model and route-facing wrappers.

- They may import `apps.contracts.*`, domain modules, and analysis evaluators.
- They should not become the source of analysis logic consumed by analysis
  modules.
- Session creation should stay injectable when a service is reused by tests or
  worker integration.

## Worker

`apps/worker/runner.py` should remain the premarket orchestration skeleton.
Specialized behavior belongs in focused modules:

- `apps/worker/step_dispatcher.py`: CME / macro / news / stub step dispatch and
  same-pipeline upstream blocking.
- `apps/worker/source_readiness_gate.py`: source readiness loading, decisions,
  blocked reasons, and events.
- `apps/worker/composite_analysis_pipeline.py`: composite agent pipeline,
  quality gate, fallback, final report, strategy card, and Gold runtime summary.
- `apps/worker/artifact_registration.py`: step, composite output, and support
  artifact registration.
- `apps/worker/report_registry_sink.py`: report registry writes.
- `apps/worker/db_persistence.py`: analysis snapshot, agent output, final result,
  and review item persistence.
- `apps/worker/error_policy.py`: error classification and retryable policy.

Runner compatibility aliases may remain while existing tests or external patch
points still depend on them, but new logic should be added to the focused
module first.

## Frontend

The frontend should consume backend read models and generated contracts rather
than duplicating backend identifiers.

- Gold identifier types are re-exported from
  `apps/frontend-web/src/types/gold-mainlines.ts`.
- Generated files are committed and guarded by
  `tests/contracts/test_frontend_gold_contract_sync.py`.
- Unknown backend status values should be normalized in adapters before they
  reach domain view-model types.

## Guards

Relevant checks:

```bash
rtk uv run pytest tests/contracts -q
rtk uv run pytest tests/architecture/test_contract_review_guards.py -q
rtk npm --prefix apps/frontend-web run typecheck
```
