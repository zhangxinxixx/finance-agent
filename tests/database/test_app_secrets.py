"""TDD: Settings secret persistence model and repository helpers."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.models.analysis import AppSecret, ensure_analysis_tables
from database.queries.app_secrets import get_app_secret, reset_app_secret, upsert_app_secret


def _make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_app_secrets_table_is_created_by_analysis_metadata() -> None:
    session = _make_session()

    tables = inspect(session.get_bind()).get_table_names()

    assert "app_secrets" in tables
    assert AppSecret.__tablename__ == "app_secrets"


def test_upsert_app_secret_stores_ciphertext_not_plaintext() -> None:
    session = _make_session()

    record = upsert_app_secret(
        session,
        source_key="fred",
        secret_name="api_key",
        encrypted_value="ciphertext-value",
        masked_value="fred****1234",
        actor="automation",
        request_id="secret-001",
        audit_id="settings-action:secret:fred:secret-001",
    )
    session.commit()

    fetched = get_app_secret(session, "fred")

    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.encrypted_value == "ciphertext-value"
    assert fetched.masked_value == "fred****1234"
    assert fetched.secret_name == "api_key"
    assert fetched.updated_by == "automation"
    assert fetched.request_id == "secret-001"
    assert fetched.audit_id == "settings-action:secret:fred:secret-001"


def test_reset_app_secret_deletes_stored_ciphertext() -> None:
    session = _make_session()
    upsert_app_secret(
        session,
        source_key="fred",
        secret_name="api_key",
        encrypted_value="ciphertext-value",
        masked_value="fred****1234",
        actor="automation",
    )
    session.commit()

    removed = reset_app_secret(session, "fred")
    session.commit()

    assert removed is True
    assert get_app_secret(session, "fred") is None
