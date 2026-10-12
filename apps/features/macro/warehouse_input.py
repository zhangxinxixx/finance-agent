"""Exact collected DWD revisions used by macro feature builders."""

from datetime import datetime

from sqlalchemy.orm import Session

from database.queries.warehouse_read import list_warehouse_macro_observations


def load_macro_feature_points(session: Session, *, record_ids: list[str], as_of: datetime) -> list[dict]:
    if not isinstance(session, Session):
        raise RuntimeError("DWD_MACRO_SESSION_REQUIRED")
    identities = list(dict.fromkeys(record_ids))
    rows = []
    for offset in range(0, len(identities), 1000):
        rows.extend(list_warehouse_macro_observations(
            session, record_ids=identities[offset:offset + 1000], as_of=as_of, limit=1000,
        ))
    if set(identities) != {row.id for row in rows}:
        missing = sorted(set(identities) - {row.id for row in rows})
        known = []
        for offset in range(0, len(missing), 1000):
            known.extend(list_warehouse_macro_observations(
                session, record_ids=missing[offset:offset + 1000], limit=1000,
            ))
        if set(missing) != {row.id for row in known}:
            raise RuntimeError("DWD_MACRO_INPUTS_MISSING")
        # Facts collected after the research cutoff are not feature inputs.
        # Callers retain source failure/time diagnostics separately.
    return [dict(
        symbol=row.symbol, date=row.observation_date.isoformat(), value=row.value,
        source=row.source_key, source_url=row.source_url, raw_path=row.raw_path,
        retrieved_at=row.retrieved_at.isoformat() if row.retrieved_at else None,
        warehouse_fact_id=row.warehouse_fact_id, version_sha256=row.version_sha256,
        quality_status=row.observation_metadata.get("quality_status"),
        reference_context=row.observation_metadata,
    ) for row in rows]
