"""Translate worker step summaries into Dagster failure semantics."""

from __future__ import annotations

from typing import Any

from dagster import Failure


def raise_for_failed_summary(step_name: str, summary: dict[str, Any]) -> None:
    """Fail the Dagster op when its delegated worker step reported failure."""
    if str(summary.get("status") or "").lower() != "failed":
        return

    detail = str(summary.get("error") or summary.get("reason") or "worker step returned failed")
    raise Failure(description=f"{step_name} failed: {detail}")
