from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.database import get_session
from app.main import create_app


@pytest.fixture
def client(tmp_path) -> Iterator[TestClient]:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    app = create_app()

    def _get_session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = _get_session_override

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
