import json
from datetime import date
from sqlalchemy import create_engine, select, func, event, inspect
from sqlalchemy.orm import sessionmaker
from database.models.analysis import MacroObservation
from database.models.task import TaskRun, TaskStep, TaskStatus
from database.models.warehouse import ensure_warehouse_tables, MacroFact, LoadBatch
from scripts.backfill_data_warehouse import main


def setup():
    engine = create_engine("sqlite:///:memory:")
    event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    for model in (MacroObservation, TaskRun, TaskStep):
        model.__table__.create(engine)
    factory = sessionmaker(engine)
    with factory.begin() as session:
        session.add(MacroObservation(id="a", source_key="fred", symbol="X", observation_date=date(2020, 1, 1), value=1))
    return engine, factory


def test_cli_default_dry_run_and_schema_missing(capsys):
    engine, factory = setup()
    statements = []
    event.listen(engine, "before_cursor_execute", lambda c, cu, s, p, ctx, many: statements.append(s))
    assert main(["--dataset", "macro", "--limit", "1"], session_factory=factory) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] and result["planned"] == 1
    assert all(s.startswith("SELECT") for s in statements)
    assert not inspect(engine).has_table("dwh_load_batch")
    assert main(["--dataset", "macro", "--apply"], session_factory=factory) == 2
    assert json.loads(capsys.readouterr().out)["error_code"] == "DWH_SCHEMA_MISSING"


def test_cli_apply_audit_cursor_repeat(capsys):
    engine, factory = setup()
    ensure_warehouse_tables(engine)
    for inserted, skipped in ((1, 0), (0, 1)):
        assert main(["--dataset", "macro", "--apply"], session_factory=factory) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["inserted"] == inserted and result["skipped"] == skipped
        assert result["task_run_id"] and result["next_after"] == "a"
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(MacroFact)) == 1
        assert session.scalar(select(func.count()).select_from(TaskRun)) == 2
        assert session.scalar(select(func.count()).select_from(LoadBatch)) == 2
    assert main(["--dataset", "macro", "--after", "a"], session_factory=factory) == 0
    assert json.loads(capsys.readouterr().out)["processed"] == 0


def test_cli_bad_bounds_and_safe_failure(capsys):
    engine, factory = setup()
    ensure_warehouse_tables(engine)
    assert main(["--dataset", "macro", "--limit", "0"], session_factory=factory) == 2
    assert json.loads(capsys.readouterr().out)["error_code"] == "DWH_ARGUMENT_INVALID"

    def broken(conn, cur, stmt, params, ctx, many):
        if stmt.startswith("INSERT INTO dwh_fact_macro"):
            raise RuntimeError("secret password and SQL full body")

    event.listen(engine, "before_cursor_execute", broken)
    assert main(["--dataset", "macro", "--apply"], session_factory=factory) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["error_code"] == "DWH_TRANSACTION_FAILED" and result["task_run_id"]
    assert "secret" not in json.dumps(result)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(MacroFact)) == 0
        assert session.scalar(select(func.count()).select_from(LoadBatch)) == 0
        assert session.scalar(select(TaskRun)).status == TaskStatus.failed
