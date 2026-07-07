from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.analysis.agents.system_evolution import SystemEvolutionReview


def persist_system_evolution_review(
    *,
    review: SystemEvolutionReview,
    storage_root: Path | str = "storage",
    trade_date: str | None = None,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    now = _ensure_utc(observed_at or datetime.now(timezone.utc))
    day = trade_date or now.date().isoformat()
    root = Path(storage_root)
    base = root / "governance" / "system_evolution" / day
    base.mkdir(parents=True, exist_ok=True)

    finding_payloads = [item.model_dump() for item in review.findings]
    proposal_payloads = [item.model_dump() for item in review.evolution_proposals]
    findings_path = base / "findings.json"
    proposals_path = base / "improvement_proposals.json"
    review_path = base / "system_evolution_review.json"

    _write_json(
        findings_path,
        {
            "trade_date": day,
            "observed_at": now.isoformat(),
            "count": len(finding_payloads),
            "findings": finding_payloads,
        },
    )
    _write_json(
        proposals_path,
        {
            "trade_date": day,
            "observed_at": now.isoformat(),
            "count": len(proposal_payloads),
            "proposals": proposal_payloads,
        },
    )
    _write_json(
        review_path,
        {
            **review.model_dump(),
            "trade_date": day,
            "observed_at": now.isoformat(),
            "artifacts": {
                "findings": _rel(findings_path, root),
                "improvement_proposals": _rel(proposals_path, root),
            },
        },
    )

    return {
        "trade_date": day,
        "observed_at": now.isoformat(),
        "review_status": review.review_status,
        "blocked": review.blocked,
        "finding_count": len(finding_payloads),
        "proposal_count": len(proposal_payloads),
        "artifacts": {
            "findings": _rel(findings_path, root),
            "improvement_proposals": _rel(proposals_path, root),
            "review": _rel(review_path, root),
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _rel(path: Path, storage_root: Path) -> str:
    try:
        return path.relative_to(storage_root).as_posix()
    except ValueError:
        return path.as_posix()
