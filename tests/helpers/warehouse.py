"""Build test DWD inputs through production ETL, never mock warehouse readers."""

from sqlalchemy import select


def create_collection_schema(engine):
    from database.models import WarehouseBase, RawSourceBase
    from database.models.task import Base
    Base.metadata.create_all(engine)
    WarehouseBase.metadata.create_all(engine)
    RawSourceBase.metadata.create_all(engine)


def materialize_candles(session, *, expected_rejected=0):
    from apps.data_layer.warehouse_etl import load_warehouse
    from database.models.analysis import MarketCandle
    create_collection_schema(session.get_bind())
    session.flush()
    ids = list(session.scalars(select(MarketCandle.id)))
    rejected = 0
    for offset in range(0, len(ids), 1000):
        result = load_warehouse(session, "candles", record_ids=ids[offset:offset + 1000], limit=1000, dry_run=False)
        rejected += result["rejected"]
    assert rejected == expected_rejected
    session.commit()


def run_macro_feature_from_dwd(state, *, storage_root, db_session=None):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from database.models.analysis import AnalysisBase
    from database.models.execution import ExecutionBase
    from apps.worker.pipelines.macro import persist_macro_points, run_macro_step
    owned = db_session is None
    engine = create_engine("sqlite://") if owned else db_session.get_bind()
    if owned:
        AnalysisBase.metadata.create_all(engine)
        ExecutionBase.metadata.create_all(engine)
        db_session = Session(engine)
    create_collection_schema(engine)
    try:
        persist_macro_points(db_session, storage_root=storage_root, all_points=state.all_points,
                             all_refs=state.all_source_refs, run_id=None)
        state.warehouse_record_ids = db_session.info["macro_warehouse_record_ids"]
        state.warehouse_status = db_session.info["macro_warehouse_ingestion"]["status"]
        return run_macro_step("macro_feature", state, storage_root=storage_root, db_session=db_session)
    finally:
        if owned:
            db_session.close()
            engine.dispose()
