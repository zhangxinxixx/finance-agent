"""Architecture guards for the #71 analysis-memory API boundary."""

from __future__ import annotations

import inspect
from pathlib import Path

from apps.api.routes import analysis_memory_routes
from apps.api.services import analysis_memory_service
from database.queries import analysis_state_observability


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_review_service_uses_the_existing_materializer_gate_only() -> None:
    source = inspect.getsource(analysis_memory_service.accept_candidate)

    assert "materialize_reviewed_transition_scoped(" in source
    assert "materialize_reviewed_transition(" in source
    assert "candidate_scope = candidate.state_scope" in source
    assert "candidate_scope != request.state_scope" in source
    assert "state_scope=candidate_scope" in source
    assert "append_analysis_state" not in source
    assert "advance_canonical_head" not in source


def test_get_routes_do_not_import_or_invoke_model_clients() -> None:
    route_source = inspect.getsource(analysis_memory_routes)
    service_source = inspect.getsource(analysis_memory_service)

    for forbidden in ("apps.llm", "LLMGateway", "chat_sync", "completions.create"):
        assert forbidden not in route_source
        assert forbidden not in service_source


def test_review_write_token_is_declared_in_env_example() -> None:
    env_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "FINANCE_AGENT_ANALYSIS_MEMORY_WRITE_TOKEN=" in env_example


def test_database_observability_queries_do_not_runtime_import_apps() -> None:
    source = inspect.getsource(analysis_state_observability)

    assert "if TYPE_CHECKING:" in source
    runtime_prefix = source.split("if TYPE_CHECKING:", maxsplit=1)[0]
    assert "from apps." not in runtime_prefix
