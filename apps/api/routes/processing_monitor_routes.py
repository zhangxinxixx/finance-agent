"""Processing monitor read-model routes."""

from __future__ import annotations

from fastapi import APIRouter

from apps.api.services.processing_monitor_service import (
    get_processing_overview,
    get_processing_trace,
    get_processing_trace_by_event,
    get_processing_trace_by_input,
    get_processing_trace_by_mainline,
    get_processing_trace_by_source_ref,
    get_processing_trace_by_transmission_chain,
)

router = APIRouter()


@router.get("/api/processing/overview")
def api_processing_overview():
    """Return the processing monitor overview read model."""
    return get_processing_overview()


@router.get("/api/processing/trace/{trace_id}")
def api_processing_trace(trace_id: str):
    """Return a processing trace by processing_trace_id."""
    return get_processing_trace(trace_id)


@router.get("/api/processing/trace-by-event/{event_id}")
def api_processing_trace_by_event(event_id: str):
    """Return a processing trace by event_id."""
    return get_processing_trace_by_event(event_id)


@router.get("/api/processing/trace-by-input/{input_id}")
def api_processing_trace_by_input(input_id: str):
    """Return a processing trace by input_id."""
    return get_processing_trace_by_input(input_id)


@router.get("/api/processing/trace-by-source-ref/{source_ref}")
def api_processing_trace_by_source_ref(source_ref: str):
    """Return a processing trace by source_ref."""
    return get_processing_trace_by_source_ref(source_ref)


@router.get("/api/processing/trace-by-mainline/{mainline}")
def api_processing_trace_by_mainline(mainline: str):
    """Return a processing trace by mainline id."""
    return get_processing_trace_by_mainline(mainline)


@router.get("/api/processing/trace-by-chain/{chain_id}")
def api_processing_trace_by_transmission_chain(chain_id: str):
    """Return a processing trace by transmission chain id."""
    return get_processing_trace_by_transmission_chain(chain_id)
