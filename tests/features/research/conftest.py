import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from tests.helpers.warehouse import create_collection_schema


@pytest.fixture
def warehouse_db():
    engine = create_engine("sqlite://")
    create_collection_schema(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()
