from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from apps.analysis.options.snapshot import build_options_snapshot
from apps.data_layer.warehouse_sources import load_source_warehouse
from database.models.cme import CmeOptionRow, CmeParseRun, CmeRawFile
from database.models.task import TaskRun, TaskStep
from database.models.warehouse import (
    LoadBatch,
    SourceDimension,
    WarehouseBase,
    ensure_warehouse_tables,
)
from database.models.warehouse_sources import CmeOptionFact
from database.queries.warehouse_cme import (
    WarehouseCmeReadError,
    build_cme_selected_lineage,
    get_available_cme_trade_dates,
    get_cme_option_rows,
    get_cme_option_rows_multi_date,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    WarehouseBase.metadata.create_all(engine)
    with sessionmaker(engine, expire_on_commit=False)() as session:
        session.add(
            SourceDimension(
                id=1,
                source_key="cme_daily_bulletin",
                source_type="official_exchange_bulletin",
                name="CME Daily Bulletin",
                url="https://www.cmegroup.com/market-data/daily-bulletin.html",
            )
        )
        session.commit()
        yield session
    engine.dispose()


def _option(
    expiry: str,
    strike: int,
    option_type: str,
    *,
    open_interest: int,
    settlement: str = "42.5",
    delta: str = "0.45",
    version_sha256: str | None = None,
    as_of: datetime | None = None,
    source_record_id: str | None = None,
) -> dict[str, object]:
    return {
        "expiry": expiry,
        "strike": strike,
        "option_type": option_type,
        "settlement": Decimal(settlement),
        "delta": Decimal(delta),
        "open_interest": open_interest,
        "oi_change": -4,
        "total_volume": 9,
        "block_volume": 1,
        "pnt_volume": 2,
        "globex_volume": 3,
        "outcry_volume": 3,
        "exercises": 0,
        "pt_change": Decimal("-1.25"),
        "source_page": 64,
        "version_sha256": version_sha256,
        "as_of": as_of,
        "source_record_id": source_record_id,
    }


def _add_bulletin(
    db: Session,
    *,
    trade_date: str,
    report_date: str | None = None,
    retrieved_at: datetime,
    version_type: str,
    rows: list[dict[str, object]],
    status: str = "loaded",
    rejected: int = 0,
    raw_id: str | None = None,
    raw_sha256: str | None = None,
) -> tuple[str, int]:
    report_date = report_date or trade_date
    raw_id = raw_id or str(uuid4())
    raw_sha256 = raw_sha256 or uuid4().hex * 2
    batch = LoadBatch(
        dataset="cme-options",
        source_cursor=raw_id,
        source_artifact_path=f"raw/cme/{raw_id}/Section64.pdf",
        source_sha256=raw_sha256,
        as_of=retrieved_at,
        producer_date=date.fromisoformat(trade_date),
        schema_version="cme-options.v1",
        rule_version=None,
        quality_status=version_type,
        source_event_count=None,
        source_trigger_count=None,
        source_rejected_count=None,
        single_source_count=None,
        multi_source_count=None,
        official_confirmed_count=None,
        unverified_count=None,
        transform_version="warehouse-collected-sources-v1",
        processed=len(rows),
        inserted=len(rows),
        skipped=0,
        rejected=rejected,
        status=status,
        error_code="DWH_INPUT_REJECTED" if rejected else None,
        audit_task_run_id=str(uuid4()),
        audit_task_step_id=str(uuid4()),
    )
    db.add(batch)
    db.flush()
    for index, values in enumerate(rows):
        fact_values = dict(values)
        version_sha = fact_values.pop("version_sha256", None) or uuid4().hex * 2
        fact_as_of = fact_values.pop("as_of", None) or retrieved_at
        source_record_id = fact_values.pop("source_record_id", None) or str(uuid4())
        db.add(
            CmeOptionFact(
                batch_id=batch.id,
                producer_run_id=None,
                version_sha256=version_sha,
                source_record_id=source_record_id,
                raw_path=batch.source_artifact_path,
                as_of=fact_as_of,
                quality_status=version_type,
                source_id=1,
                source_raw_id=raw_id,
                source_url="https://www.cmegroup.com/bulletin.pdf",
                raw_sha256=raw_sha256,
                retrieved_at=retrieved_at,
                parse_status=version_type,
                trade_date=date.fromisoformat(trade_date),
                report_date=date.fromisoformat(report_date),
                version_type=version_type,
                product_code="OG",
                underlying="GC",
                **fact_values,
            )
        )
    db.commit()
    return raw_id, batch.id


def test_date_discovery_does_not_load_numerical_payloads_and_full_read_still_does(db):
    _add_bulletin(
        db,
        trade_date="2026-10-08",
        retrieved_at=datetime(2026, 10, 9, 1, tzinfo=UTC),
        version_type="FINAL",
        rows=[_option("DEC26", 4400, "CALL", open_interest=123, settlement="42.5")],
    )
    db.expunge_all()
    selected_columns = []

    def record_columns(_connection, cursor, statement, _parameters, _context, _executemany):
        if "FROM dwh_fact_cme_option JOIN" in statement:
            selected_columns.append({column[0] for column in cursor.description})

    event.listen(db.bind, "after_cursor_execute", record_columns)
    try:
        assert get_available_cme_trade_dates(db) == ["2026-10-08"]
        assert len(selected_columns) == 2  # Date candidates and their authority metadata.
        assert all(not {"settlement", "open_interest", "delta", "total_volume"} & columns
                   for columns in selected_columns)
        rows = get_cme_option_rows(db, report_date="2026-10-08")
        assert rows[0].settlement == Decimal("42.5")
        assert rows[0].open_interest == 123
    finally:
        event.remove(db.bind, "after_cursor_execute", record_columns)


@pytest.mark.parametrize("blocked", ["rejected-latest", "ambiguous-source", "parse-phase-mismatch"])
def test_date_discovery_keeps_full_read_rejection_semantics(db, blocked):
    instant = datetime(2026, 10, 9, 1, tzinfo=UTC)
    raw_id, _ = _add_bulletin(
        db, trade_date="2026-10-08", retrieved_at=instant, version_type="FINAL",
        rows=[_option("DEC26", 4400, "CALL", open_interest=100)],
    )
    if blocked == "rejected-latest":
        batch = db.scalar(select(LoadBatch).where(LoadBatch.source_cursor == raw_id))
        batch.rejected = 1
        batch.error_code = "DWH_INPUT_REJECTED"
    elif blocked == "ambiguous-source":
        _add_bulletin(
            db, trade_date="2026-10-08", retrieved_at=instant, version_type="FINAL",
            rows=[_option("DEC26", 4500, "CALL", open_interest=200)],
        )
    else:
        fact = db.scalar(select(CmeOptionFact))
        fact.parse_status = "UNVERIFIED"
    db.commit()
    db.expunge_all()
    with pytest.raises(WarehouseCmeReadError) as numerical:
        get_cme_option_rows(db, report_date="2026-10-08")
    db.expunge_all()
    with pytest.raises(WarehouseCmeReadError) as dates:
        get_available_cme_trade_dates(db)
    assert str(dates.value) == str(numerical.value)


def test_final_revision_is_one_bulletin_and_does_not_double_count_oi(db):
    _add_bulletin(
        db,
        trade_date="2026-10-08",
        retrieved_at=datetime(2026, 10, 9, 1, tzinfo=UTC),
        version_type="PRELIMINARY",
        rows=[_option("DEC26", 4400, "CALL", open_interest=90)],
    )
    _add_bulletin(
        db,
        trade_date="2026-10-08",
        retrieved_at=datetime(2026, 10, 9, 2, tzinfo=UTC),
        version_type="FINAL",
        rows=[
            _option("DEC26", 4400, "CALL", open_interest=100),
            _option("DEC26", 4400, "PUT", open_interest=200),
        ],
    )
    newest_raw_id, newest_batch_id = _add_bulletin(
        db,
        trade_date="2026-10-08",
        retrieved_at=datetime(2026, 10, 9, 3, tzinfo=UTC),
        version_type="FINAL",
        rows=[
            _option("DEC26", 4500, "CALL", open_interest=170),
            _option("DEC26", 4500, "PUT", open_interest=230),
        ],
    )

    rows = get_cme_option_rows(db, report_date="2026-10-08", product="og")

    assert [(row.strike, row.option_type, row.open_interest) for row in rows] == [
        (4500, "CALL", 170),
        (4500, "PUT", 230),
    ]
    assert {row.raw_file_id for row in rows} == {newest_raw_id}
    assert {row.batch_id for row in rows} == {newest_batch_id}
    assert sum(row.open_interest or 0 for row in rows) == 400
    assert rows[0].id == rows[0].source_record_id
    assert rows[0].warehouse_fact_id > 0 and len(rows[0].version_sha256) == 64


def test_pit_uses_source_availability_preserves_utc_and_builds_typed_lineage(db):
    prelim_raw, _ = _add_bulletin(
        db,
        trade_date="2026-10-08",
        retrieved_at=datetime(2026, 10, 9, 1, tzinfo=UTC),
        version_type="PRELIMINARY",
        rows=[_option("DEC26", 4500, "CALL", open_interest=80)],
    )
    final_raw, _ = _add_bulletin(
        db,
        trade_date="2026-10-08",
        retrieved_at=datetime(2026, 10, 9, 2, tzinfo=UTC),
        version_type="FINAL",
        rows=[_option("DEC26", 4500, "CALL", open_interest=120)],
    )

    prelim = get_cme_option_rows(
        db,
        report_date="2026-10-08",
        as_of=datetime(2026, 10, 9, 1, 30, tzinfo=UTC),
    )
    final = get_cme_option_rows(
        db,
        report_date="2026-10-08",
        as_of=datetime(2026, 10, 9, 2, 30, tzinfo=UTC),
    )
    lineage = build_cme_selected_lineage(final)

    assert (prelim[0].version_type, prelim[0].raw_file_id) == ("PRELIMINARY", prelim_raw)
    assert (final[0].version_type, final[0].raw_file_id) == ("FINAL", final_raw)
    assert final[0].retrieved_at.tzinfo == UTC and final[0].as_of.tzinfo == UTC
    assert lineage["raw_file_ids"] == [final_raw]
    assert lineage["parse_run_ids"] == []
    assert lineage["source_refs"][0]["source_kind"] == "dwd_typed_fact"
    assert lineage["source_refs"][0]["warehouse_fact_ids"] == [final[0].warehouse_fact_id]
    with pytest.raises(WarehouseCmeReadError, match="DWD_CME_PIT_INVALID"):
        get_cme_option_rows(db, report_date="2026-10-08", as_of=datetime(2026, 10, 9, 2))


def test_business_revision_is_latest_once_within_one_bulletin(db):
    raw_id = str(uuid4())
    source_record_id = str(uuid4())
    sha = "a" * 64
    retrieved = datetime(2026, 10, 9, 2, tzinfo=UTC)
    _add_bulletin(
        db,
        trade_date="2026-10-08",
        retrieved_at=retrieved,
        version_type="FINAL",
        raw_id=raw_id,
        raw_sha256=sha,
        rows=[
            _option(
                "DEC26",
                4500,
                "CALL",
                open_interest=100,
                version_sha256="b" * 64,
                as_of=retrieved,
                source_record_id=source_record_id,
            ),
            _option(
                "DEC26",
                4500,
                "CALL",
                open_interest=125,
                version_sha256="c" * 64,
                as_of=datetime(2026, 10, 9, 2, 5, tzinfo=UTC),
                source_record_id=source_record_id,
            ),
        ],
    )

    rows = get_cme_option_rows(
        db,
        report_date="2026-10-08",
        as_of=datetime(2026, 10, 9, 2, 10, tzinfo=UTC),
    )

    assert len(rows) == 1
    assert (rows[0].open_interest, rows[0].version_sha256) == (125, "c" * 64)


def test_same_grain_different_source_rows_and_tied_bulletins_are_ambiguous(db):
    raw_id = str(uuid4())
    sha = "d" * 64
    retrieved = datetime(2026, 10, 9, 2, tzinfo=UTC)
    _add_bulletin(
        db,
        trade_date="2026-10-08",
        retrieved_at=retrieved,
        version_type="FINAL",
        raw_id=raw_id,
        raw_sha256=sha,
        rows=[
            _option("DEC26", 4500, "CALL", open_interest=100),
            _option("DEC26", 4500, "CALL", open_interest=125),
        ],
    )

    with pytest.raises(WarehouseCmeReadError, match="DWD_CME_REVISION_AMBIGUOUS"):
        get_cme_option_rows(db, report_date="2026-10-08")

    other_db_date = "2026-10-07"
    _add_bulletin(
        db,
        trade_date=other_db_date,
        retrieved_at=retrieved,
        version_type="FINAL",
        rows=[_option("DEC26", 4400, "CALL", open_interest=80)],
    )
    _add_bulletin(
        db,
        trade_date=other_db_date,
        retrieved_at=retrieved,
        version_type="FINAL",
        rows=[_option("DEC26", 4400, "PUT", open_interest=90)],
    )
    with pytest.raises(WarehouseCmeReadError, match="DWD_CME_BULLETIN_AMBIGUOUS"):
        get_cme_option_rows(db, report_date=other_db_date)


def test_real_etl_incremental_revision_keeps_unchanged_contract_and_blocks_unsafe_pit():
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    for table in (
        TaskRun.__table__,
        TaskStep.__table__,
        CmeRawFile.__table__,
        CmeOptionRow.__table__,
        CmeParseRun.__table__,
    ):
        table.create(engine, checkfirst=True)
    ensure_warehouse_tables(engine)
    retrieved = datetime(2026, 10, 9, 2, tzinfo=UTC)
    raw_id = str(uuid4())
    call_id, put_id = str(uuid4()), str(uuid4())
    try:
        with sessionmaker(engine, expire_on_commit=False)() as session:
            session.add(
                CmeRawFile(
                    id=raw_id,
                    source="cme_daily_bulletin",
                    section="PG64",
                    source_url="https://www.cmegroup.com/bulletin.pdf",
                    raw_path="raw/cme/2026-10-08/Section64.pdf",
                    sha256="e" * 64,
                    report_date="2026-10-08",
                    bytes=12,
                    retrieved_at=retrieved,
                )
            )
            session.flush()
            session.add(
                CmeParseRun(
                    raw_file_id=raw_id,
                    status="FINAL",
                    detail_rows_count=2,
                    summary_rows_count=0,
                    created_at=retrieved,
                )
            )
            session.add_all(
                [
                    CmeOptionRow(
                        id=call_id,
                        raw_file_id=raw_id,
                        trade_date="2026-10-08",
                        report_date="2026-10-08",
                        version_type="FINAL",
                        product_code="OG",
                        underlying="GC",
                        expiry="DEC26",
                        strike=4500,
                        option_type="CALL",
                        settlement=42.5,
                        delta=0.45,
                        open_interest=100,
                    ),
                    CmeOptionRow(
                        id=put_id,
                        raw_file_id=raw_id,
                        trade_date="2026-10-08",
                        report_date="2026-10-08",
                        version_type="FINAL",
                        product_code="OG",
                        underlying="GC",
                        expiry="DEC26",
                        strike=4500,
                        option_type="PUT",
                        settlement=38.5,
                        delta=-0.55,
                        open_interest=43,
                    ),
                ]
            )
            session.commit()

            first = load_source_warehouse(
                session,
                "cme-options",
                record_ids=[raw_id],
                dry_run=False,
            )
            session.commit()
            assert (first["inserted"], first["skipped"]) == (2, 0)

            call = session.scalar(select(CmeOptionRow).where(CmeOptionRow.id == call_id))
            assert call is not None
            call.open_interest = 107
            session.commit()
            revised = load_source_warehouse(
                session,
                "cme-options",
                record_ids=[raw_id],
                dry_run=False,
            )
            session.commit()

            rows = get_cme_option_rows(session, report_date="2026-10-08")
            lineage = build_cme_selected_lineage(rows)

            assert (revised["inserted"], revised["skipped"]) == (1, 1)
            assert [(row.option_type, row.open_interest) for row in rows] == [
                ("CALL", 107),
                ("PUT", 43),
            ]
            assert sum(row.open_interest or 0 for row in rows) == 150
            assert {row.source_record_id for row in rows} == {call_id, put_id}
            assert len({row.batch_id for row in rows}) == 2
            assert len(lineage["source_refs"]) == 1
            assert lineage["source_refs"][0]["warehouse_batch_ids"] == sorted(
                {row.batch_id for row in rows}
            )
            with pytest.raises(WarehouseCmeReadError, match="DWD_CME_REVISION_AMBIGUOUS"):
                get_cme_option_rows(
                    session,
                    report_date="2026-10-08",
                    as_of=datetime(2026, 10, 9, 3, tzinfo=UTC),
                )
    finally:
        engine.dispose()


def test_multi_date_selects_each_date_independently_and_bad_final_blocks_own_scope(db):
    _add_bulletin(
        db,
        trade_date="2026-10-07",
        retrieved_at=datetime(2026, 10, 8, 1, tzinfo=UTC),
        version_type="PRELIMINARY",
        rows=[_option("DEC26", 4400, "CALL", open_interest=70)],
    )
    _add_bulletin(
        db,
        trade_date="2026-10-08",
        retrieved_at=datetime(2026, 10, 9, 1, tzinfo=UTC),
        version_type="FINAL",
        rows=[_option("DEC26", 4500, "CALL", open_interest=80)],
    )

    result = get_cme_option_rows_multi_date(
        db,
        trade_dates=["2026-10-08", "2026-10-07"],
    )

    assert result["2026-10-08"][0].version_type == "FINAL"
    assert result["2026-10-07"][0].version_type == "PRELIMINARY"
    assert get_available_cme_trade_dates(db, limit=2) == ["2026-10-08", "2026-10-07"]

    _add_bulletin(
        db,
        trade_date="2026-10-07",
        retrieved_at=datetime(2026, 10, 8, 2, tzinfo=UTC),
        version_type="FINAL",
        status="partial",
        rejected=1,
        rows=[_option("DEC26", 4400, "CALL", open_interest=999)],
    )
    # The other date remains independently readable; including the bad date
    # blocks instead of falling back to its PRELIMINARY rows.
    assert get_cme_option_rows(db, report_date="2026-10-08")[0].open_interest == 80
    with pytest.raises(WarehouseCmeReadError, match="DWD_CME_QUALITY_BLOCKED"):
        get_cme_option_rows(db, report_date="2026-10-07")
    with pytest.raises(WarehouseCmeReadError, match="DWD_CME_QUALITY_BLOCKED"):
        get_cme_option_rows_multi_date(
            db,
            trade_dates=["2026-10-08", "2026-10-07"],
        )


def test_trade_date_uses_latest_report_revision_without_splicing_older_contracts(db):
    _add_bulletin(
        db,
        trade_date="2026-10-08",
        report_date="2026-10-08",
        retrieved_at=datetime(2026, 10, 9, 1, tzinfo=UTC),
        version_type="FINAL",
        rows=[_option("DEC26", 4400, "CALL", open_interest=70)],
    )
    _add_bulletin(
        db,
        trade_date="2026-10-08",
        report_date="2026-10-11",
        retrieved_at=datetime(2026, 10, 11, 2, tzinfo=UTC),
        version_type="PRELIMINARY",
        rows=[_option("DEC26", 4550, "CALL", open_interest=999)],
    )
    _add_bulletin(
        db,
        trade_date="2026-10-08",
        report_date="2026-10-10",
        retrieved_at=datetime(2026, 10, 10, 2, tzinfo=UTC),
        version_type="FINAL",
        rows=[_option("DEC26", 4500, "PUT", open_interest=80)],
    )

    multi = get_cme_option_rows_multi_date(db, trade_dates=["2026-10-08"])
    original_report = get_cme_option_rows(db, report_date="2026-10-08")

    assert [(row.report_date, row.strike) for row in multi["2026-10-08"]] == [("2026-10-10", 4500)]
    assert [(row.report_date, row.strike) for row in original_report] == [("2026-10-08", 4400)]


def test_reader_never_queries_ods_price_or_parsed_storage(db):
    _add_bulletin(
        db,
        trade_date="2026-10-08",
        retrieved_at=datetime(2026, 10, 9, 2, tzinfo=UTC),
        version_type="FINAL",
        rows=[_option("DEC26", 4500, "CALL", open_interest=120)],
    )
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.lower())

    event.listen(db.get_bind(), "before_cursor_execute", capture)
    try:
        get_cme_option_rows(db, report_date="2026-10-08")
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", capture)

    sql = "\n".join(statements)
    assert "dwh_fact_cme_option" in sql and "dwh_load_batch" in sql
    assert "cme_option_rows" not in sql
    assert "cme_raw_files" not in sql
    assert "json_" not in sql and "->" not in sql


def test_reparse_keeps_one_parser_edition_and_pit_before_reparse(db):
    initial = datetime(2026, 10, 9, 1, tzinfo=UTC)
    revised = datetime(2026, 10, 9, 2, tzinfo=UTC)
    raw_id, _ = _add_bulletin(db, trade_date="2026-10-08", retrieved_at=initial,
        version_type="FINAL", raw_sha256="c" * 64,
        rows=[_option("DEC26", 4400, "CALL", open_interest=10, source_record_id="old-call"),
              _option("DEC26", 4400, "PUT", open_interest=20, source_record_id="removed-put")])
    _, batch_id = _add_bulletin(db, trade_date="2026-10-08", retrieved_at=initial,
        version_type="FINAL", raw_id=raw_id, raw_sha256="c" * 64,
        rows=[_option("DEC26", 4400, "CALL", open_interest=15, source_record_id="new-call", as_of=revised)])
    db.get(LoadBatch, batch_id).as_of = revised
    db.flush()
    assert [(r.option_type, r.open_interest) for r in get_cme_option_rows(db, report_date="2026-10-08")] == [("CALL", 15)]
    assert sum(r.open_interest for r in get_cme_option_rows(db, report_date="2026-10-08", as_of=initial)) == 30


def test_failed_empty_reparse_blocks_older_good_facts(db):
    raw_id, _ = _add_bulletin(db, trade_date="2026-10-08", retrieved_at=datetime(2026, 10, 9, 1, tzinfo=UTC),
        version_type="FINAL", raw_sha256="b" * 64,
        rows=[_option("DEC26", 4400, "CALL", open_interest=10)])
    _add_bulletin(db, trade_date="2026-10-08", retrieved_at=datetime(2026, 10, 9, 2, tzinfo=UTC),
        version_type="FINAL", raw_id=raw_id, raw_sha256="b" * 64, rows=[], status="rejected", rejected=1)
    with pytest.raises(WarehouseCmeReadError, match="DWD_CME_QUALITY_BLOCKED"):
        get_cme_option_rows(db, report_date="2026-10-08")


def test_dwd_rows_preserve_production_feature_numerics(db):
    source_rows = [
        _option("DEC26", 4400, "CALL", open_interest=100, settlement="120", delta="0.60"),
        _option("DEC26", 4400, "PUT", open_interest=180, settlement="60", delta="0.40"),
        _option("DEC26", 4600, "CALL", open_interest=220, settlement="55", delta="0.35"),
        _option("DEC26", 4600, "PUT", open_interest=140, settlement="115", delta="0.65"),
    ]
    _add_bulletin(
        db,
        trade_date="2026-10-08",
        retrieved_at=datetime(2026, 10, 9, 2, tzinfo=UTC),
        version_type="FINAL",
        rows=source_rows,
    )
    dwd_rows = get_cme_option_rows(db, report_date="2026-10-08")
    dwd_payload = [row.to_dict() for row in dwd_rows]
    original_payload = [
        {
            **{key: value for key, value in row.items() if key not in {"version_sha256", "as_of"}},
            "trade_date": "2026-10-08",
            "report_date": "2026-10-08",
            "version_type": "FINAL",
            "product_code": "OG",
            "underlying": "GC",
        }
        for row in source_rows
    ]

    dwd_result = build_options_snapshot(
        dwd_payload,
        trade_date="2026-10-08",
        p0=4500.0,
        user_f=4500.0,
        data_source_status="FINAL",
    )
    original_result = build_options_snapshot(
        original_payload,
        trade_date="2026-10-08",
        p0=4500.0,
        user_f=4500.0,
        data_source_status="FINAL",
    )

    assert dwd_result.normalized_rows == original_result.normalized_rows
    assert dwd_result.exposures == original_result.exposures
    assert dwd_result.netgex == original_result.netgex


def test_missing_schema_missing_facts_and_bounds_fail_closed(db):
    with pytest.raises(WarehouseCmeReadError, match="DWD_CME_ARGUMENT_INVALID"):
        get_cme_option_rows(db)
    with pytest.raises(WarehouseCmeReadError, match="DWD_CME_FACTS_MISSING"):
        get_cme_option_rows(db, report_date="2026-10-08")
    with pytest.raises(WarehouseCmeReadError, match="DWD_CME_ARGUMENT_INVALID"):
        get_available_cme_trade_dates(db, limit=101)
    with pytest.raises(WarehouseCmeReadError, match="DWD_CME_ARGUMENT_INVALID"):
        get_cme_option_rows_multi_date(db, trade_dates=[])
    with pytest.raises(WarehouseCmeReadError, match="DWD_CME_ARGUMENT_INVALID"):
        get_cme_option_rows_multi_date(db, trade_dates=[None])  # type: ignore[list-item]
    with pytest.raises(WarehouseCmeReadError, match="DWD_CME_ARGUMENT_INVALID"):
        get_cme_option_rows_multi_date(
            db,
            trade_dates=["2026-10-08"],
            prefer_final="yes",  # type: ignore[arg-type]
        )

    engine = create_engine("sqlite:///:memory:")
    try:
        with Session(engine) as empty_db:
            with pytest.raises(WarehouseCmeReadError, match="DWD_CME_SCHEMA_MISSING"):
                get_cme_option_rows(empty_db, report_date="2026-10-08")
    finally:
        engine.dispose()
