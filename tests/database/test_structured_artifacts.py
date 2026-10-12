import uuid
import re

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session

from database.models.execution import RunArtifact, ensure_execution_tables
from database.queries.structured_artifacts import list_structured_artifacts, structured_artifact_coverage
from apps.runtime.artifact_registry import list_run_artifacts


def test_additive_upgrade_preserves_old_row_and_is_repeatable():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE run_artifacts (artifact_id UUID PRIMARY KEY, run_id UUID NOT NULL, task_id UUID, artifact_type VARCHAR(64) NOT NULL, file_path TEXT NOT NULL)"
            )
        )
        conn.execute(
            text("INSERT INTO run_artifacts VALUES ('old-artifact','old-run',NULL,'raw_file','raw/macro/old.json')")
        )
    ensure_execution_tables(engine)
    ensure_execution_tables(engine)
    columns = {c["name"] for c in inspect(engine).get_columns("run_artifacts")}
    assert {
        "structured_payload",
        "structured_payload_sha256",
        "structured_layer",
        "structured_schema_version",
        "structured_status",
        "structured_error",
    } <= columns
    with engine.connect() as conn:
        row = conn.execute(text("SELECT artifact_id,run_id,file_path,structured_status FROM run_artifacts")).one()
        assert tuple(row) == ("old-artifact", "old-run", "raw/macro/old.json", None)
    names = {index["name"] for index in inspect(engine).get_indexes("run_artifacts")}
    assert "ix_run_artifacts_structured_coverage" in names


def test_query_filters_coverage_and_cursor():
    engine = create_engine("sqlite://")
    ensure_execution_tables(engine)
    run_id, other = uuid.uuid4(), uuid.uuid4()
    with Session(engine) as db:
        for n in range(3):
            db.add(
                RunArtifact(
                    run_id=run_id if n < 2 else other,
                    artifact_type="feature_json",
                    file_path=f"features/test/{n}.json",
                    structured_payload={"n": n},
                    structured_status="persisted",
                    structured_layer="features",
                    structured_schema_version="test.v1",
                )
            )
        db.commit()
        first = list_structured_artifacts(
            db, run_ids=[run_id], layer="features", status="persisted", schema_version="test.v1", limit=1
        )
        second = list_structured_artifacts(db, run_ids=[run_id], after=first[0].artifact_id, limit=1)
        assert len(first) == len(second) == 1
        assert first[0].artifact_id != second[0].artifact_id
        assert structured_artifact_coverage(db, run_ids=[run_id])["total"] == 2


def test_existing_metadata_listing_does_not_fetch_structured_bodies():
    engine = create_engine("sqlite://")
    ensure_execution_tables(engine)
    run_id = uuid.uuid4()
    body = {"records": ["macro observation"] * 10000}
    with Session(engine) as db:
        db.add(
            RunArtifact(
                run_id=run_id,
                artifact_type="feature_json",
                file_path="features/test/body.json",
                structured_payload=body,
                structured_status="persisted",
            )
        )
        db.commit()
    statements = []
    event.listen(
        engine, "before_cursor_execute", lambda conn, cursor, sql, params, context, many: statements.append(sql)
    )
    with Session(engine) as db:
        assert len(list_run_artifacts(db, str(run_id))) == 1
        assert all(re.search(r"run_artifacts\.structured_payload", sql) is None for sql in statements)
        assert list_structured_artifacts(db, run_ids=[run_id], limit=1)[0].structured_payload == body
