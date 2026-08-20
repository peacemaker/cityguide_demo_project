import sqlite3
from pathlib import Path
import pytest

# Starter tests. The hidden bugs are intentionally not covered yet.


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app as application

    db = tmp_path / "test.db"
    monkeypatch.setattr(application, "DB_PATH", db)
    application.init_db()

    application.app.config["TESTING"] = True
    with application.app.test_client() as client:
        yield client


def test_homepage(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Old Town Square" in response.data


def test_place_details(client):
    response = client.get("/place/1")
    assert response.status_code == 200
    assert b"Old Town Square" in response.data
