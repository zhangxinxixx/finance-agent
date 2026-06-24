"""TDD: Playbook registry persistence and version history."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.models.analysis import ensure_analysis_tables
from database.models.playbook import PlaybookTemplate
from database.queries.playbooks import (
    create_playbook_template,
    get_playbook_template,
    get_playbook_template_detail,
    list_playbook_templates,
    list_playbook_template_versions,
)


def _make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _create_playbook(session: Session, *, version: str, title: str = "Range breakout long") -> None:
    create_playbook_template(
        session,
        playbook_id="pb-range-breakout-long",
        version=version,
        status="draft",
        title=title,
        summary="Use when price breaks the upper range with confirmation.",
        conditions=["price_breaks_range_high", "volume_confirms"],
        actions=["watch", "confirm", "avoid_chasing"],
        invalidations=["wallscore_too_high"],
        source_refs=[{"source_ref": "playbook.range_breakout"}],
        last_validated="2026-05-30T08:00:00Z",
        actor="automation",
        reason="seed test template",
        request_id=f"pb-seed-{version}",
        audit_id=f"settings-action:playbook:pb-range-breakout-long:{version}",
    )
    session.commit()


def test_playbook_templates_table_is_created_by_analysis_metadata() -> None:
    session = _make_session()

    tables = inspect(session.get_bind()).get_table_names()

    assert "playbook_templates" in tables
    assert PlaybookTemplate.__tablename__ == "playbook_templates"


def test_create_playbook_template_persists_latest_version_and_history() -> None:
    session = _make_session()
    _create_playbook(session, version="v1.0")
    _create_playbook(session, version="v1.1", title="Range breakout long v1.1")

    latest = get_playbook_template(session, "pb-range-breakout-long")
    detail = get_playbook_template_detail(session, "pb-range-breakout-long")
    registry = list_playbook_templates(session)
    versions = list_playbook_template_versions(session, "pb-range-breakout-long")

    assert latest is not None
    assert latest.playbook_id == "pb-range-breakout-long"
    assert latest.version == "v1.1"
    assert detail is not None
    assert detail["playbook_id"] == "pb-range-breakout-long"
    assert detail["version"] == "v1.1"
    assert detail["versions"][0]["version"] == "v1.1"
    assert registry[0]["version"] == "v1.1"
    assert [item.version for item in versions] == ["v1.1", "v1.0"]


def test_create_playbook_template_rejects_duplicate_version() -> None:
    session = _make_session()
    _create_playbook(session, version="v1.0")

    try:
        _create_playbook(session, version="v1.0", title="duplicate")
    except ValueError as exc:
        assert "duplicate" in str(exc).lower()
        return

    raise AssertionError("Expected duplicate version to be rejected")
