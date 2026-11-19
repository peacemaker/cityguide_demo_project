import sqlite3
from pathlib import Path

import pytest

# Starter tests. The hidden bugs are intentionally not covered yet.


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    import app as application

    db = tmp_path / "test.db"
    monkeypatch.setattr(application, "DB_PATH", db)
    application.init_db()

    application.app.config["TESTING"] = True
    yield application, db


@pytest.fixture
def client(app_module):
    application, _db = app_module
    with application.app.test_client() as client:
        yield client


def _review_rows(db_path: Path, place_id=None):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if place_id is None:
            rows = conn.execute(
                "SELECT place_id, review_text FROM reviews ORDER BY id"
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT place_id, review_text
                FROM reviews
                WHERE place_id = ?
                ORDER BY id
                """,
                (place_id,),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _review_texts(db_path: Path, place_id: int):
    return [row["review_text"] for row in _review_rows(db_path, place_id)]


def test_homepage(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Old Town Square" in response.data


def test_place_details(client):
    response = client.get("/place/1")
    assert response.status_code == 200
    assert b"Old Town Square" in response.data


def test_ac01_active_place_detail_shows_review_submission_area(client):
    response = client.get("/place/1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Reviews" in html
    assert "Share your experience" in html
    assert "method=\"post\"" in html.lower()
    assert "name=\"review_text\"" in html
    assert "Submit review" in html


def test_ac02_anonymous_non_empty_review_submission_is_persisted(client, app_module):
    _application, db_path = app_module
    review_text = "A calm afternoon among lovely architecture."

    response = client.post("/place/1", data={"review_text": review_text})

    assert response.status_code in {200, 302, 303}
    assert "/login" not in response.headers.get("Location", "").lower()
    assert review_text in _review_texts(db_path, 1)


def test_ac03_submitted_review_is_visible_to_fresh_visitor_session(client, app_module):
    application, _db_path = app_module
    review_text = "Fresh visitor can read this Old Town Square review."
    client.post("/place/1", data={"review_text": review_text})

    with application.app.test_client() as other_visitor:
        response = other_visitor.get("/place/1")

    assert response.status_code == 200
    assert review_text in response.get_data(as_text=True)


def test_ac04_reviews_are_scoped_to_their_place(client):
    square_review = "Old Town Square has wonderful evening lights."
    park_review = "Riverside Park is peaceful for morning walks."

    client.post("/place/1", data={"review_text": square_review})
    client.post("/place/2", data={"review_text": park_review})

    square_page = client.get("/place/1").get_data(as_text=True)
    park_page = client.get("/place/2").get_data(as_text=True)

    assert square_review in square_page
    assert park_review not in square_page
    assert park_review in park_page
    assert square_review not in park_page


def test_ac05_blank_review_is_rejected_and_not_saved(client, app_module):
    _application, db_path = app_module

    response = client.post("/place/1", data={"review_text": "   \n\t   "})

    assert response.status_code in {200, 400, 422}
    feedback = response.get_data(as_text=True).lower()
    assert any(
        phrase in feedback
        for phrase in (
            "please enter",
            "required",
            "cannot be blank",
            "error",
            "review before submitting",
        )
    )
    assert _review_rows(db_path, 1) == []

    reloaded_page = client.get("/place/1").get_data(as_text=True)
    assert "0 reviews" in reloaded_page or "No reviews yet" in reloaded_page


def test_ac06_review_remains_available_after_new_database_connection(client, app_module):
    application, db_path = app_module
    review_text = "Persistence check after the creating request completes."

    post_response = client.post("/place/1", data={"review_text": review_text})
    assert post_response.status_code in {200, 302, 303}

    assert review_text in _review_texts(db_path, 1)

    with application.app.test_client() as fresh_client:
        response = fresh_client.get("/place/1")

    assert response.status_code == 200
    assert review_text in response.get_data(as_text=True)


def test_ac07_review_text_is_escaped_when_rendered(client):
    review_text = "<script>alert(1)</script><strong>great visit</strong>"

    response = client.post(
        "/place/1",
        data={"review_text": review_text},
        follow_redirects=True,
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert "<strong>great visit</strong>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;strong&gt;great visit&lt;/strong&gt;" in html


def test_ac08_review_submission_rejects_nonexistent_and_inactive_places(client, app_module):
    _application, db_path = app_module
    attempted_review = "This review must not be saved for an unavailable place."

    for place_id in (999999, 5):
        response = client.post(
            f"/place/{place_id}",
            data={"review_text": attempted_review},
        )

        assert response.status_code in {400, 404, 410}
        assert _review_rows(db_path, place_id) == []

    assert attempted_review not in [row["review_text"] for row in _review_rows(db_path)]


def test_ac09_empty_reviews_state_loads_cleanly(client):
    response = client.get("/place/1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Reviews" in html
    assert "Internal Server Error" not in html
    assert "Traceback" not in html
    assert (
        "No reviews yet" in html
        or "0 reviews" in html
        or ("name=\"review_text\"" in html and "Submit review" in html)
    )
