"""Resolve the canonical daily-close predecessor for one target bundle."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from apps.analysis.gold_policy.daily_close_store import (
    DailyCloseHeadLookup,
    load_gold_daily_close_head,
)


class CanonicalPredecessorResolver:
    """Use one date-boundary rule for controls and daily-close execution.

    A new bundle may extend the current session's revision chain.  An existing
    target bundle is excluded with its whole session so an idempotent reread
    cannot select itself as the predecessor.
    """

    def __init__(self, *, storage_root: Path) -> None:
        self._storage_root = storage_root

    def resolve(
        self,
        *,
        session_date: date,
        target_bundle_path: Path,
    ) -> DailyCloseHeadLookup:
        before_date = session_date if target_bundle_path.exists() else session_date + timedelta(days=1)
        return load_gold_daily_close_head(
            storage_root=self._storage_root,
            before_date=before_date,
        )


def resolve_canonical_predecessor(
    *,
    storage_root: Path,
    session_date: date,
    target_bundle_path: Path,
) -> DailyCloseHeadLookup:
    """Resolve the canonical predecessor for a specific daily-close bundle."""

    return CanonicalPredecessorResolver(storage_root=storage_root).resolve(
        session_date=session_date,
        target_bundle_path=target_bundle_path,
    )
