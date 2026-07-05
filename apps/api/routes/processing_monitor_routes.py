"""Processing monitor read-model routes."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/processing/overview")
def api_processing_overview():
    """Return the processing monitor overview read model."""
    from apps.api import main as api_main

    return api_main.get_processing_overview()


@router.get("/api/processing/trace/{trace_id}")
def api_processing_trace(trace_id: str):
    """Return a processing trace by processing_trace_id."""
    from apps.api import main as api_main

    return api_main.get_processing_trace(trace_id)


@router.get("/api/processing/trace-by-event/{event_id}")
def api_processing_trace_by_event(event_id: str):
    """Return a processing trace by event_id."""
    from apps.api import main as api_main

    return api_main.get_processing_trace_by_event(event_id)


@router.get("/api/processing/trace-by-input/{input_id}")
def api_processing_trace_by_input(input_id: str):
    """Return a processing trace by input_id."""
    from apps.api import main as api_main

    return api_main.get_processing_trace_by_input(input_id)


@router.get("/api/processing/trace-by-source-ref/{source_ref}")
def api_processing_trace_by_source_ref(source_ref: str):
    """Return a processing trace by source_ref."""
    from apps.api import main as api_main

    return api_main.get_processing_trace_by_source_ref(source_ref)


@router.get("/api/processing/trace-by-mainline/{mainline}")
def api_processing_trace_by_mainline(mainline: str):
    """Return a processing trace by mainline id."""
    from apps.api import main as api_main

    return api_main.get_processing_trace_by_mainline(mainline)


@router.get("/api/processing/trace-by-chain/{chain_id}")
def api_processing_trace_by_transmission_chain(chain_id: str):
    """Return a processing trace by transmission chain id."""
    from apps.api import main as api_main

    return api_main.get_processing_trace_by_transmission_chain(chain_id)
