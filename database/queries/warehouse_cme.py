"""Read-only CME option facts from the typed DWD warehouse.

This module is deliberately independent of the legacy CME ODS models.  A
selected result always comes from one bulletin identity; PRELIMINARY and FINAL
rows, or rows from different source files, are never combined into one view.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Iterable, Sequence

from sqlalchemy import inspect, select
from sqlalchemy.orm import Load, Session, aliased

from database.models.warehouse import LoadBatch
from database.models.warehouse_sources import CmeOptionFact


class WarehouseCmeReadError(RuntimeError):
    """A stable, fail-closed DWD CME read failure."""


@dataclass(frozen=True, slots=True)
class WarehouseCmeOptionRow:
    """Named DWD DTO compatible with the option-analysis row contract."""

    id: str
    warehouse_fact_id: int
    batch_id: int
    producer_run_id: int | None
    version_sha256: str
    source_record_id: str
    raw_file_id: str
    source_raw_id: str
    raw_sha256: str
    source_url: str | None
    raw_path: str | None
    retrieved_at: datetime
    as_of: datetime | None
    quality_status: str | None
    parse_status: str | None
    trade_date: str
    report_date: str
    version_type: str
    product_code: str
    underlying: str | None
    expiry: str
    strike: int
    option_type: str
    settlement: Decimal | None
    delta: Decimal | None
    open_interest: int | None
    oi_change: int | None
    total_volume: int | None
    block_volume: int | None
    pnt_volume: int | None
    globex_volume: int | None
    outcry_volume: int | None
    exercises: int | None
    pt_change: Decimal | None
    source_page: int | None

    def to_dict(self) -> dict[str, object]:
        """Return the named row shape consumed by existing feature code."""

        return asdict(self)


_REQUIRED_TABLES = {CmeOptionFact.__tablename__, LoadBatch.__tablename__}
_MAX_MULTI_DATES = 64
_MAX_AVAILABLE_DATES = 100
_VALID_VERSIONS = {"FINAL", "PRELIMINARY"}


def _fail(code: str) -> None:
    raise WarehouseCmeReadError(code)


def _check_schema(session: Session) -> None:
    try:
        inspector = inspect(session.connection())
        if any(not inspector.has_table(table) for table in _REQUIRED_TABLES):
            _fail("DWD_CME_SCHEMA_MISSING")
        fact_columns = {column["name"] for column in inspector.get_columns(CmeOptionFact.__tablename__)}
        batch_columns = {column["name"] for column in inspector.get_columns(LoadBatch.__tablename__)}
    except WarehouseCmeReadError:
        raise
    except Exception:
        _fail("DWD_CME_SCHEMA_MISSING")
    required_fact_columns = {column.name for column in CmeOptionFact.__table__.columns}
    required_batch_columns = {"id", "dataset", "as_of", "quality_status", "status", "rejected", "error_code"}
    if not required_fact_columns <= fact_columns or not required_batch_columns <= batch_columns:
        _fail("DWD_CME_SCHEMA_MISSING")


def _iso_date(value: str | date | None, *, name: str) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        _fail("DWD_CME_ARGUMENT_INVALID")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    _fail("DWD_CME_ARGUMENT_INVALID")


def _pit(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _fail("DWD_CME_PIT_INVALID")
    return value.astimezone(UTC)


def _product(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 16:
        _fail("DWD_CME_ARGUMENT_INVALID")
    return value.strip().upper()


def _version(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value.strip().upper() not in _VALID_VERSIONS:
        _fail("DWD_CME_VERSION_INVALID")
    return value.strip().upper()


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _read_facts(
    session: Session,
    *,
    product: str,
    report_date: date | None = None,
    trade_dates: Sequence[date] | None = None,
    as_of: datetime | None = None,
    selection_only: bool = False,
) -> list[tuple[CmeOptionFact, LoadBatch]]:
    receipt = aliased(LoadBatch)
    latest_receipt = select(receipt.id).where(
        receipt.dataset == "cme-options", receipt.source_cursor == CmeOptionFact.source_raw_id,
    )
    if as_of is not None:
        latest_receipt = latest_receipt.where((receipt.as_of.is_(None)) | (receipt.as_of <= as_of))
    latest_receipt = latest_receipt.order_by(receipt.id.desc()).limit(1).correlate(CmeOptionFact).scalar_subquery()
    statement = (
        select(CmeOptionFact, LoadBatch)
        .join(LoadBatch, LoadBatch.id == latest_receipt)
        .where(CmeOptionFact.product_code == product)
        .where(LoadBatch.dataset == "cme-options")
    )
    if selection_only:
        # Date discovery applies the same bulletin/edition/quality/revision
        # rules as a numerical read. It needs provenance and contract grain,
        # but loading every settlement/Greek/volume and batch audit payload
        # for all advertised dates adds substantial work with no consumer.
        statement = statement.options(
            Load(CmeOptionFact).load_only(
                CmeOptionFact.id, CmeOptionFact.trade_date, CmeOptionFact.report_date,
                CmeOptionFact.version_type, CmeOptionFact.source_raw_id,
                CmeOptionFact.raw_sha256, CmeOptionFact.retrieved_at, CmeOptionFact.as_of,
                CmeOptionFact.parse_status, CmeOptionFact.quality_status,
                CmeOptionFact.source_url, CmeOptionFact.raw_path,
                CmeOptionFact.expiry, CmeOptionFact.strike, CmeOptionFact.option_type,
                CmeOptionFact.source_record_id, CmeOptionFact.version_sha256,
                raiseload=True,
            ),
            Load(LoadBatch).load_only(
                LoadBatch.id, LoadBatch.status, LoadBatch.rejected,
                LoadBatch.error_code, LoadBatch.quality_status,
                raiseload=True,
            ),
        )
    if report_date is not None:
        statement = statement.where(CmeOptionFact.report_date == report_date)
    if trade_dates is not None:
        statement = statement.where(CmeOptionFact.trade_date.in_(trade_dates))
    if as_of is not None:
        # retrieved_at/as_of are source-availability fields.  load_time is an
        # ingestion timestamp and must never become the point-in-time clock.
        statement = statement.where(CmeOptionFact.retrieved_at <= as_of)
        statement = statement.where((CmeOptionFact.as_of.is_(None)) | (CmeOptionFact.as_of <= as_of))
        statement = statement.where((LoadBatch.as_of.is_(None)) | (LoadBatch.as_of <= as_of))
    statement = statement.order_by(
        CmeOptionFact.trade_date,
        CmeOptionFact.report_date,
        CmeOptionFact.retrieved_at,
        CmeOptionFact.id,
    )
    return [(fact, batch) for fact, batch in session.execute(statement)]


def _bulletin_key(fact: CmeOptionFact) -> tuple[object, ...]:
    # A load batch is an ETL execution, not a bulletin identity.  Incremental
    # re-loads legitimately leave unchanged contracts in an older batch while
    # appending only revised contracts in a newer batch.
    return (
        fact.trade_date,
        fact.version_type,
        fact.source_raw_id,
        fact.raw_sha256,
    )


def _business_key(fact: CmeOptionFact) -> tuple[str, int, str]:
    return fact.expiry, fact.strike, fact.option_type


def _availability(rows: Sequence[tuple[CmeOptionFact, LoadBatch]]) -> datetime:
    values = [_utc(fact.retrieved_at) for fact, _ in rows]
    if not values or any(value is None for value in values):
        _fail("DWD_CME_SOURCE_TIME_MISSING")
    return max(value for value in values if value is not None)


def _eligible(rows: Sequence[tuple[CmeOptionFact, LoadBatch]], version_type: str) -> bool:
    retrieved_times = {_utc(fact.retrieved_at) for fact, _ in rows}
    source_urls = {fact.source_url for fact, _ in rows}
    raw_paths = {fact.raw_path for fact, _ in rows}
    return (
        bool(rows)
        and len(retrieved_times) == 1
        and len(source_urls) == 1
        and len(raw_paths) == 1
        and all(
            batch.status == "loaded"
            and int(batch.rejected or 0) == 0
            and batch.error_code is None
            and fact.version_type == version_type
            and fact.parse_status == version_type
            and fact.quality_status == version_type
            and batch.quality_status == version_type
            for fact, batch in rows
        )
    )


def _select_scope(
    rows: Sequence[tuple[CmeOptionFact, LoadBatch]],
    *,
    version_type: str | None,
    pit_query: bool,
) -> list[CmeOptionFact]:
    versions = {fact.version_type for fact, _ in rows}
    if not rows:
        _fail("DWD_CME_FACTS_MISSING")
    unknown = versions - _VALID_VERSIONS
    if unknown:
        _fail("DWD_CME_QUALITY_BLOCKED")
    chosen_version = version_type or ("FINAL" if "FINAL" in versions else "PRELIMINARY")
    phase_rows = [(fact, batch) for fact, batch in rows if fact.version_type == chosen_version]
    if not phase_rows:
        _fail("DWD_CME_FACTS_MISSING")

    bulletins: dict[tuple[object, ...], list[tuple[CmeOptionFact, LoadBatch]]] = {}
    for item in phase_rows:
        bulletins.setdefault(_bulletin_key(item[0]), []).append(item)
    ranked = sorted(
        ((_availability(items), key, items) for key, items in bulletins.items()),
        key=lambda item: item[0],
        reverse=True,
    )
    latest_time = ranked[0][0]
    latest = [item for item in ranked if item[0] == latest_time]
    if len(latest) != 1:
        _fail("DWD_CME_BULLETIN_AMBIGUOUS")
    selected = latest[0][2]
    # All rows of one parser edition share its source availability time. A
    # reparse can remove contracts, so older editions must not fill its gaps.
    edition = max(_utc(fact.as_of) or _utc(fact.retrieved_at) for fact, _ in selected)
    selected = [(fact, batch) for fact, batch in selected
                if (_utc(fact.as_of) or _utc(fact.retrieved_at)) == edition]
    if not _eligible(selected, chosen_version):
        # Do not hide a rejected/partial newer FINAL behind an older FINAL or
        # PRELIMINARY bulletin.
        _fail("DWD_CME_QUALITY_BLOCKED")

    by_business_key: dict[tuple[str, int, str], list[CmeOptionFact]] = {}
    for fact, _ in selected:
        by_business_key.setdefault(_business_key(fact), []).append(fact)
    result: list[CmeOptionFact] = []
    for facts in by_business_key.values():
        if len(facts) == 1:
            result.append(facts[0])
            continue
        # Two different source rows claiming the same option grain are not a
        # revision chain we can prove.  Do not use row order to hide that
        # source conflict.
        revision_times = [(_utc(fact.as_of) or _utc(fact.retrieved_at), fact) for fact in facts]
        latest_revision = max(item[0] for item in revision_times if item[0] is not None)
        winners = [fact for revision_time, fact in revision_times if revision_time == latest_revision]
        if len(winners) == 1:
            result.append(winners[0])
            continue
        if len({fact.source_record_id for fact in winners}) != 1:
            _fail("DWD_CME_REVISION_AMBIGUOUS")
        # The current ETL can append a same-source-row correction without a
        # newer source availability timestamp.  A current read may choose the
        # last append deterministically, but an as_of query must not leak that
        # later correction into history when its effective time is unknown.
        if pit_query and len({fact.version_sha256 for fact in winners}) != 1:
            _fail("DWD_CME_REVISION_AMBIGUOUS")
        result.append(max(winners, key=lambda fact: fact.id))
    return sorted(result, key=lambda fact: (fact.expiry, fact.strike, fact.option_type))


def _select_by_date_scope(
    rows: Sequence[tuple[CmeOptionFact, LoadBatch]],
    *,
    version_type: str | None,
    pit_query: bool,
) -> list[CmeOptionFact]:
    by_trade_date: dict[date, dict[date, list[tuple[CmeOptionFact, LoadBatch]]]] = {}
    for item in rows:
        fact = item[0]
        by_trade_date.setdefault(fact.trade_date, {}).setdefault(fact.report_date, []).append(item)
    if not by_trade_date:
        _fail("DWD_CME_FACTS_MISSING")
    selected: list[CmeOptionFact] = []
    for trade_date in sorted(by_trade_date):
        report_versions = by_trade_date[trade_date]
        available_versions = {fact.version_type for items in report_versions.values() for fact, _ in items}
        if available_versions - _VALID_VERSIONS:
            _fail("DWD_CME_QUALITY_BLOCKED")
        chosen_version = version_type or ("FINAL" if "FINAL" in available_versions else "PRELIMINARY")
        candidate_reports = {
            report_date: items
            for report_date, items in report_versions.items()
            if any(fact.version_type == chosen_version for fact, _ in items)
        }
        if not candidate_reports:
            _fail("DWD_CME_FACTS_MISSING")
        # FINAL preference applies across report revisions.  Within that
        # phase, a later report_date revises this trade_date; never fill its
        # missing contracts from an older report.
        selected.extend(
            _select_scope(
                candidate_reports[max(candidate_reports)],
                version_type=chosen_version,
                pit_query=pit_query,
            )
        )
    return selected


def _dto(fact: CmeOptionFact) -> WarehouseCmeOptionRow:
    retrieved_at = _utc(fact.retrieved_at)
    if retrieved_at is None:
        _fail("DWD_CME_SOURCE_TIME_MISSING")
    return WarehouseCmeOptionRow(
        id=fact.source_record_id,
        warehouse_fact_id=fact.id,
        batch_id=fact.batch_id,
        producer_run_id=fact.producer_run_id,
        version_sha256=fact.version_sha256,
        source_record_id=fact.source_record_id,
        raw_file_id=fact.source_raw_id,
        source_raw_id=fact.source_raw_id,
        raw_sha256=fact.raw_sha256,
        source_url=fact.source_url,
        raw_path=fact.raw_path,
        retrieved_at=retrieved_at,
        as_of=_utc(fact.as_of),
        quality_status=fact.quality_status,
        parse_status=fact.parse_status,
        trade_date=fact.trade_date.isoformat(),
        report_date=fact.report_date.isoformat(),
        version_type=fact.version_type,
        product_code=fact.product_code,
        underlying=fact.underlying,
        expiry=fact.expiry,
        strike=fact.strike,
        option_type=fact.option_type,
        settlement=fact.settlement,
        delta=fact.delta,
        open_interest=fact.open_interest,
        oi_change=fact.oi_change,
        total_volume=fact.total_volume,
        block_volume=fact.block_volume,
        pnt_volume=fact.pnt_volume,
        globex_volume=fact.globex_volume,
        outcry_volume=fact.outcry_volume,
        exercises=fact.exercises,
        pt_change=fact.pt_change,
        source_page=fact.source_page,
    )


def get_cme_option_rows(
    session: Session,
    *,
    report_date: str | date | None = None,
    product: str = "OG",
    expiries: set[str] | None = None,
    version_type: str | None = None,
    as_of: datetime | None = None,
) -> list[WarehouseCmeOptionRow]:
    """Return FINAL-preferred rows from one DWD bulletin per date scope."""

    _check_schema(session)
    normalized_date = _iso_date(report_date, name="report_date")
    if normalized_date is None:
        # The legacy signature permits None, but every real worker/API
        # consumer supplies a date.  Rejecting None keeps the DWD scan bounded.
        _fail("DWD_CME_ARGUMENT_INVALID")
    normalized_product = _product(product)
    normalized_version = _version(version_type)
    cutoff = _pit(as_of)
    if expiries is not None and (
        not isinstance(expiries, (set, frozenset))
        or not expiries
        or len(expiries) > 64
        or any(not isinstance(value, str) or not value.strip() for value in expiries)
    ):
        _fail("DWD_CME_ARGUMENT_INVALID")
    selected = _select_by_date_scope(
        _read_facts(
            session,
            product=normalized_product,
            report_date=normalized_date,
            as_of=cutoff,
        ),
        version_type=normalized_version,
        pit_query=cutoff is not None,
    )
    if expiries is not None:
        wanted = {value.strip().upper() for value in expiries}
        selected = [fact for fact in selected if fact.expiry.upper() in wanted]
        if not selected:
            _fail("DWD_CME_FACTS_MISSING")
    return [_dto(fact) for fact in selected]


def get_cme_option_rows_multi_date(
    session: Session,
    *,
    trade_dates: list[str | date],
    product: str = "OG",
    prefer_final: bool = True,
    as_of: datetime | None = None,
) -> dict[str, list[WarehouseCmeOptionRow]]:
    """Return independently selected, whole-bulletin rows for bounded dates."""

    _check_schema(session)
    if (
        not isinstance(trade_dates, list)
        or not trade_dates
        or len(trade_dates) > _MAX_MULTI_DATES
        or type(prefer_final) is not bool
    ):
        _fail("DWD_CME_ARGUMENT_INVALID")
    normalized_dates = [_iso_date(value, name="trade_date") for value in trade_dates]
    if any(value is None for value in normalized_dates) or len(set(normalized_dates)) != len(normalized_dates):
        _fail("DWD_CME_ARGUMENT_INVALID")
    dates = [value for value in normalized_dates if value is not None]
    cutoff = _pit(as_of)
    rows = _read_facts(
        session,
        product=_product(product),
        trade_dates=dates,
        as_of=cutoff,
    )
    by_trade_date: dict[date, list[tuple[CmeOptionFact, LoadBatch]]] = {}
    for item in rows:
        by_trade_date.setdefault(item[0].trade_date, []).append(item)
    if set(by_trade_date) != set(dates):
        _fail("DWD_CME_FACTS_MISSING")
    result: dict[str, list[WarehouseCmeOptionRow]] = {}
    for trade_date in dates:
        selected = _select_by_date_scope(
            by_trade_date[trade_date],
            version_type=None if prefer_final else "PRELIMINARY",
            pit_query=cutoff is not None,
        )
        result[trade_date.isoformat()] = [_dto(fact) for fact in selected]
    return result


def get_available_cme_trade_dates(
    session: Session,
    *,
    product: str = "OG",
    limit: int = 10,
    as_of: datetime | None = None,
) -> list[str]:
    """Return newest selectable DWD trade dates, with a bounded result."""

    _check_schema(session)
    if type(limit) is not int or not 1 <= limit <= _MAX_AVAILABLE_DATES:
        _fail("DWD_CME_ARGUMENT_INVALID")
    normalized_product = _product(product)
    cutoff = _pit(as_of)
    date_statement = (
        select(CmeOptionFact.trade_date)
        .join(LoadBatch, LoadBatch.id == CmeOptionFact.batch_id)
        .where(CmeOptionFact.product_code == normalized_product)
        .where(LoadBatch.dataset == "cme-options")
    )
    if cutoff is not None:
        date_statement = date_statement.where(CmeOptionFact.retrieved_at <= cutoff)
        date_statement = date_statement.where((CmeOptionFact.as_of.is_(None)) | (CmeOptionFact.as_of <= cutoff))
        date_statement = date_statement.where((LoadBatch.as_of.is_(None)) | (LoadBatch.as_of <= cutoff))
    date_statement = date_statement.distinct().order_by(CmeOptionFact.trade_date.desc()).limit(limit)
    dates = list(session.scalars(date_statement))
    if not dates:
        _fail("DWD_CME_FACTS_MISSING")
    rows = _read_facts(
        session,
        product=normalized_product,
        trade_dates=dates,
        as_of=cutoff,
        selection_only=True,
    )
    by_trade_date: dict[date, list[tuple[CmeOptionFact, LoadBatch]]] = {}
    for item in rows:
        by_trade_date.setdefault(item[0].trade_date, []).append(item)
    # Validate every advertised date under the same FINAL-preferred rules.  A
    # bad newest revision is surfaced, never silently omitted from discovery.
    for trade_date in dates:
        _select_by_date_scope(
            by_trade_date[trade_date],
            version_type=None,
            pit_query=cutoff is not None,
        )
    return [value.isoformat() for value in dates]


def build_cme_selected_lineage(
    rows: Iterable[WarehouseCmeOptionRow],
) -> dict[str, object]:
    """Build worker-compatible lineage directly from selected typed facts."""

    materialized = list(rows)
    refs: list[dict[str, object]] = []
    grouped: dict[tuple[str, str], list[WarehouseCmeOptionRow]] = {}
    for row in materialized:
        grouped.setdefault((row.raw_file_id, row.raw_sha256), []).append(row)
    for (_, _), group in sorted(grouped.items()):
        first = group[0]
        batch_ids = sorted({row.batch_id for row in group})
        refs.append(
            {
                "source": "cme_daily_bulletin",
                "source_kind": "dwd_typed_fact",
                "raw_file_id": first.raw_file_id,
                "raw_path": first.raw_path,
                "source_url": first.source_url,
                "sha256": first.raw_sha256,
                "report_date": first.report_date,
                "trade_date": first.trade_date,
                "version_type": first.version_type,
                "retrieved_at": first.retrieved_at.isoformat(),
                "warehouse_batch_id": batch_ids[-1],
                "warehouse_batch_ids": batch_ids,
                "warehouse_fact_ids": sorted(row.warehouse_fact_id for row in group),
                "source_record_ids": sorted(row.source_record_id for row in group),
                "version_sha256s": sorted({row.version_sha256 for row in group}),
            }
        )
    return {
        "raw_file_ids": sorted({row.raw_file_id for row in materialized}),
        "raw_file_sha256s": sorted({row.raw_sha256 for row in materialized}),
        "parse_run_ids": [],
        "source_urls": sorted({row.source_url for row in materialized if row.source_url}),
        "source_refs": refs,
    }


__all__ = [
    "WarehouseCmeOptionRow",
    "WarehouseCmeReadError",
    "build_cme_selected_lineage",
    "get_available_cme_trade_dates",
    "get_cme_option_rows",
    "get_cme_option_rows_multi_date",
]
