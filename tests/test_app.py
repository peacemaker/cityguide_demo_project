import html
import sqlite3

import pytest


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "cityguide-test.db"


@pytest.fixture
def app_module(db_path, monkeypatch):
    import app as application

    monkeypatch.setattr(application, "DB_PATH", db_path)
    application.init_db()
    application.app.config["TESTING"] = True
    yield application


@pytest.fixture
def client(app_module):
    with app_module.app.test_client() as test_client:
        yield test_client


def _review_texts(db_path, place_id):
    conn = sqlite3.connect(db_path)
    try:
        return [
            row[0]
            for row in conn.execute(
                "SELECT review_text FROM reviews WHERE place_id = ? ORDER BY id ASC",
                (place_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def _all_review_rows(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT place_id, review_text FROM reviews ORDER BY id ASC"
        ).fetchall()
    finally:
        conn.close()


def _assert_review_form_available(response):
    page = response.data.lower()
    assert b"review" in page
    assert b"<textarea" in page
    assert b"review_text" in page


def test_homepage_browsing_still_lists_active_places(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"Old Town Square" in response.data
    assert b"Riverside Park" in response.data
    assert b"Science Museum" in response.data
    assert b"Central Market" in response.data
    assert b"Hidden Gallery" not in response.data

    search_response = client.get("/", query_string={"q": "Park"})

    assert search_response.status_code == 200
    assert b"Riverside Park" in search_response.data
    assert b"Old Town Square" not in search_response.data


def test_place_details_includes_reviews_section_when_empty_and_preserves_place_fields(client):
    response = client.get("/place/1")

    assert response.status_code == 200
    assert b"Old Town Square" in response.data
    assert b"Historic" in response.data
    assert b"Kyiv" in response.data
    assert b"A lively historic square with caf" in response.data
    assert b"4.8" in response.data
    assert b"review" in response.data.lower()
    assert b"no review" in response.data.lower() or b"be the first" in response.data.lower()
    _assert_review_form_available(response)


def test_visitor_can_submit_review_without_login_and_other_client_can_read_it(client, app_module):
    review_text = "Loved the atmosphere around the square after sunset."

    submitted = client.post(
        "/place/1",
        data={"review_text": review_text},
        follow_redirects=True,
    )

    assert submitted.status_code == 200
    assert review_text.encode() in submitted.data
    assert b"Old Town Square" in submitted.data

    with app_module.app.test_client() as other_visitor:
        other_response = other_visitor.get("/place/1")

    assert other_response.status_code == 200
    assert review_text.encode() in other_response.data


def test_submitted_review_persists_after_refresh_and_new_database_connection(client, app_module, db_path):
    review_text = "Persistence check: this written review should remain available."

    post_response = client.post(
        "/place/1",
        data={"review_text": review_text},
        follow_redirects=True,
    )
    refreshed_response = client.get("/place/1")
    persisted_texts = _review_texts(db_path, 1)

    assert post_response.status_code == 200
    assert refreshed_response.status_code == 200
    assert review_text.encode() in refreshed_response.data
    assert persisted_texts == [review_text]

    with app_module.app.test_client() as new_session_client:
        new_session_response = new_session_client.get("/place/1")

    assert new_session_response.status_code == 200
    assert review_text.encode() in new_session_response.data


def test_reviews_display_only_for_their_submission_place(client):
    square_review = "Square-only review for isolation acceptance."
    park_review = "Park-only review for isolation acceptance."

    assert client.post("/place/1", data={"review_text": square_review}).status_code in (302, 303)
    assert client.post("/place/2", data={"review_text": park_review}).status_code in (302, 303)

    square_page = client.get("/place/1")
    park_page = client.get("/place/2")

    assert square_page.status_code == 200
    assert park_page.status_code == 200
    assert square_review.encode() in square_page.data
    assert park_review.encode() not in square_page.data
    assert park_review.encode() in park_page.data
    assert square_review.encode() not in park_page.data


def test_empty_and_whitespace_reviews_are_rejected_with_feedback(client, db_path):
    empty_response = client.post(
        "/place/1",
        data={"review_text": ""},
        follow_redirects=True,
    )
    whitespace_response = client.post(
        "/place/1",
        data={"review_text": "   \n\t   "},
        follow_redirects=True,
    )

    assert empty_response.status_code == 200
    assert whitespace_response.status_code == 200
    _assert_review_form_available(empty_response)
    _assert_review_form_available(whitespace_response)
    assert _review_texts(db_path, 1) == []

    valid_review = "A real written review after rejected blank submissions."
    valid_response = client.post(
        "/place/1",
        data={"review_text": valid_review},
        follow_redirects=True,
    )

    assert valid_response.status_code == 200
    assert valid_review.encode() in valid_response.data
    assert _review_texts(db_path, 1) == [valid_review]


def test_review_text_is_escaped_not_rendered_as_html(client):
    review_text = "<script>alert(1)</script><em>amazing</em> & memorable"

    response = client.post(
        "/place/1",
        data={"review_text": review_text},
        follow_redirects=True,
    )

    escaped_review = html.escape(review_text, quote=False).encode()
    assert response.status_code == 200
    assert review_text.encode() not in response.data
    assert escaped_review in response.data
    assert b"<script>alert(1)</script>" not in response.data.lower()
    assert b"&lt;em&gt;amazing&lt;/em&gt;" in response.data


def test_reviews_are_rejected_for_nonexistent_and_inactive_places(client, db_path):
    assert client.get("/place/9999").status_code == 404
    assert client.post(
        "/place/9999",
        data={"review_text": "This must not create an orphan review."},
    ).status_code == 404

    assert client.get("/place/5").status_code == 404
    assert client.post(
        "/place/5",
        data={"review_text": "This inactive-place review must be rejected."},
    ).status_code == 404

    assert _all_review_rows(db_path) == []


def test_init_db_adds_reviews_table_without_overwriting_existing_places(tmp_path, monkeypatch):
    import app as application

    existing_db = tmp_path / "existing-cityguide.db"
    conn = sqlite3.connect(existing_db)
    try:
        conn.executescript(
            """
            CREATE TABLE places (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                city TEXT NOT NULL,
                rating REAL NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        conn.execute(
            """
            INSERT INTO places (id, name, category, description, city, rating, active)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "Old Town Square",
                "Historic",
                "Existing database description that must survive review initialization.",
                "Kyiv",
                3.3,
                1,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(application, "DB_PATH", existing_db)
    application.init_db()

    conn = sqlite3.connect(existing_db)
    conn.row_factory = sqlite3.Row
    try:
        place = conn.execute(
            "SELECT name, category, description, city, rating, active FROM places WHERE id = 1"
        ).fetchone()
        assert place is not None
        assert place["name"] == "Old Town Square"
        assert place["category"] == "Historic"
        assert place["description"] == "Existing database description that must survive review initialization."
        assert place["city"] == "Kyiv"
        assert place["rating"] == 3.3
        assert place["active"] == 1
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'reviews'"
        ).fetchone() is not None
    finally:
        conn.close()

    application.app.config["TESTING"] = True
    review_text = "Review submitted after additive initialization."
    with application.app.test_client() as existing_db_client:
        detail_response = existing_db_client.get("/place/1")
        submit_response = existing_db_client.post(
            "/place/1",
            data={"review_text": review_text},
            follow_redirects=True,
        )

    assert detail_response.status_code == 200
    assert b"Existing database description" in detail_response.data
    _assert_review_form_available(detail_response)
    assert submit_response.status_code == 200
    assert review_text.encode() in submit_response.data
