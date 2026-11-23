import re
import sqlite3
from pathlib import Path

import pytest
from werkzeug.datastructures import MultiDict


@pytest.fixture
def application():
    import app as application_module

    application_module.app.config["TESTING"] = True
    return application_module


@pytest.fixture
def client(tmp_path, monkeypatch, application):
    db_path = tmp_path / "cityguide.db"
    monkeypatch.setattr(application, "DB_PATH", db_path)
    application.init_db()

    with application.app.test_client() as test_client:
        test_client.db_path = db_path
        yield test_client


def place_row(
    row_id,
    name,
    rating,
    *,
    rating_count=1,
    active=1,
    category="Test",
    description=None,
    city="Kyiv",
):
    return {
        "id": row_id,
        "name": name,
        "category": category,
        "description": description or f"Description for {name}",
        "city": city,
        "rating": rating,
        "rating_count": rating_count,
        "active": active,
    }


def create_places_db(db_path: Path, rows, *, include_rating_count=True):
    conn = sqlite3.connect(db_path)
    try:
        rating_count_column = (
            ", rating_count INTEGER NOT NULL DEFAULT 1" if include_rating_count else ""
        )
        conn.execute(
            f"""
            CREATE TABLE places (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                city TEXT NOT NULL,
                rating REAL NOT NULL
                {rating_count_column},
                active INTEGER NOT NULL DEFAULT 1
            )
            """
        )

        if include_rating_count:
            conn.executemany(
                """
                INSERT INTO places
                    (id, name, category, description, city, rating, rating_count, active)
                VALUES
                    (:id, :name, :category, :description, :city, :rating, :rating_count, :active)
                """,
                rows,
            )
        else:
            conn.executemany(
                """
                INSERT INTO places
                    (id, name, category, description, city, rating, active)
                VALUES
                    (:id, :name, :category, :description, :city, :rating, :active)
                """,
                rows,
            )
        conn.commit()
    finally:
        conn.close()


def configure_custom_db(tmp_path, monkeypatch, application, rows):
    db_path = tmp_path / "cityguide.db"
    monkeypatch.setattr(application, "DB_PATH", db_path)
    create_places_db(db_path, rows)
    return db_path


def read_place(db_path, place_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT id, name, rating, rating_count, active FROM places WHERE id = ?",
            (place_id,),
        ).fetchone()
    finally:
        conn.close()


def assert_rating_state(db_path, place_id, expected_rating, expected_count):
    place = read_place(db_path, place_id)
    assert place is not None
    assert place["rating"] == pytest.approx(expected_rating)
    assert place["rating_count"] == expected_count


def assert_page_shows_rating_and_count(html, name, expected_rating, expected_count):
    assert name in html
    assert f"{expected_rating:.1f}" in html
    rating_word = "rating" if expected_count == 1 else "ratings"
    assert f"{expected_count} {rating_word}" in html


def stats_text(html):
    match = re.search(r"<section[^>]*class=\"stats\"[^>]*>(.*?)</section>", html, re.S)
    assert match, "homepage stats section was not rendered"
    text = re.sub(r"<[^>]+>", " ", match.group(1))
    return " ".join(text.split())


def assert_homepage_average(html, expected_average):
    expected_text = f"{expected_average:.1f} average rating"
    assert expected_text in stats_text(html)


def test_init_db_backfills_rating_count_for_all_existing_places_preserves_decimal_ratings(
    tmp_path, monkeypatch, application
):
    db_path = tmp_path / "legacy_cityguide.db"
    legacy_rows = [
        place_row(10, "Legacy Decimal Park", 4.25, active=1),
        place_row(11, "Legacy Inactive Gallery", 3.75, active=0),
    ]
    create_places_db(db_path, legacy_rows, include_rating_count=False)
    monkeypatch.setattr(application, "DB_PATH", db_path)

    application.init_db()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(places)")}
        assert "rating_count" in columns

        active_place = conn.execute(
            "SELECT rating, rating_count, active FROM places WHERE id = 10"
        ).fetchone()
        inactive_place = conn.execute(
            "SELECT rating, rating_count, active FROM places WHERE id = 11"
        ).fetchone()
    finally:
        conn.close()

    assert active_place["active"] == 1
    assert active_place["rating"] == pytest.approx(4.25)
    assert active_place["rating_count"] == 1

    assert inactive_place["active"] == 0
    assert inactive_place["rating"] == pytest.approx(3.75)
    assert inactive_place["rating_count"] == 1


def test_browse_and_detail_show_average_rating_and_rating_count(client):
    homepage = client.get("/")
    assert homepage.status_code == 200
    homepage_html = homepage.get_data(as_text=True)

    assert_page_shows_rating_and_count(homepage_html, "Old Town Square", 4.8, 1)
    assert_page_shows_rating_and_count(homepage_html, "Riverside Park", 4.5, 1)
    assert "Hidden Gallery" not in homepage_html

    detail = client.get("/place/1")
    assert detail.status_code == 200
    detail_html = detail.get_data(as_text=True)
    assert_page_shows_rating_and_count(detail_html, "Old Town Square", 4.8, 1)

    assert "Rate this place" in detail_html
    for stars in range(1, 6):
        assert f'name="rating" value="{stars}"' in detail_html
    assert 'name="rating" value="0"' not in detail_html
    assert 'name="rating" value="6"' not in detail_html


def test_valid_unauthenticated_rating_updates_cumulative_average_and_count(
    tmp_path, monkeypatch, application
):
    db_path = configure_custom_db(
        tmp_path,
        monkeypatch,
        application,
        [place_row(1, "Cumulative Cafe", 4.0, rating_count=1, active=1)],
    )

    with application.app.test_client() as test_client:
        first_response = test_client.post("/place/1/rate", data={"rating": "2"})
        assert first_response.status_code in {302, 303}
        assert_rating_state(db_path, 1, 3.0, 2)

        second_response = test_client.post("/place/1/rate", data={"rating": "5"})
        assert second_response.status_code in {302, 303}

    assert_rating_state(db_path, 1, (4.0 + 2.0 + 5.0) / 3.0, 3)


def test_invalid_rating_submissions_are_rejected_without_changing_data(
    tmp_path, monkeypatch, application
):
    db_path = configure_custom_db(
        tmp_path,
        monkeypatch,
        application,
        [place_row(1, "Validation Museum", 4.5, rating_count=1, active=1)],
    )

    invalid_submissions = [
        {},
        {"rating": ""},
        {"rating": "five"},
        {"rating": "0"},
        {"rating": "6"},
        {"rating": "4.5"},
        MultiDict([("rating", "4"), ("rating", "5")]),
    ]

    with application.app.test_client() as test_client:
        for payload in invalid_submissions:
            response = test_client.post("/place/1/rate", data=payload)
            assert response.status_code >= 400
            assert_rating_state(db_path, 1, 4.5, 1)


def test_updated_rating_is_consistent_across_detail_homepage_and_search(
    tmp_path, monkeypatch, application
):
    db_path = configure_custom_db(
        tmp_path,
        monkeypatch,
        application,
        [
            place_row(1, "Consistent Plaza", 4.0, rating_count=1, active=1),
            place_row(2, "Other Place", 2.0, rating_count=1, active=1),
        ],
    )

    with application.app.test_client() as test_client:
        response = test_client.post("/place/1/rate", data={"rating": "5"})
        assert response.status_code in {302, 303}

        for path in ("/place/1", "/", "/?q=Consistent"):
            refreshed = test_client.get(path)
            assert refreshed.status_code == 200
            assert_page_shows_rating_and_count(
                refreshed.get_data(as_text=True), "Consistent Plaza", 4.5, 2
            )

    assert_rating_state(db_path, 1, 4.5, 2)


def test_rating_update_persists_in_same_database_across_app_reinitialization(
    tmp_path, monkeypatch, application
):
    db_path = configure_custom_db(
        tmp_path,
        monkeypatch,
        application,
        [place_row(1, "Persistent Gardens", 4.0, rating_count=1, active=1)],
    )

    with application.app.test_client() as first_client:
        response = first_client.post("/place/1/rate", data={"rating": "5"})
        assert response.status_code in {302, 303}

    assert_rating_state(db_path, 1, 4.5, 2)

    application.init_db()

    with application.app.test_client() as second_client:
        detail = second_client.get("/place/1")
        assert detail.status_code == 200
        assert_page_shows_rating_and_count(
            detail.get_data(as_text=True), "Persistent Gardens", 4.5, 2
        )

    assert_rating_state(db_path, 1, 4.5, 2)


def test_homepage_overall_average_excludes_inactive_places_and_remains_unweighted(
    tmp_path, monkeypatch, application
):
    configure_custom_db(
        tmp_path,
        monkeypatch,
        application,
        [
            place_row(1, "Many Ratings Low", 1.0, rating_count=100, active=1),
            place_row(2, "One Rating High", 5.0, rating_count=1, active=1),
            place_row(3, "Inactive Outlier", 5.0, rating_count=1, active=0),
        ],
    )

    with application.app.test_client() as test_client:
        response = test_client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Many Ratings Low" in html
    assert "One Rating High" in html
    assert "Inactive Outlier" not in html
    assert_homepage_average(html, 3.0)


def test_homepage_overall_average_is_sitewide_not_search_filtered(
    tmp_path, monkeypatch, application
):
    configure_custom_db(
        tmp_path,
        monkeypatch,
        application,
        [
            place_row(1, "Search Target", 5.0, rating_count=1, active=1),
            place_row(2, "Unmatched Active Place", 1.0, rating_count=1, active=1),
            place_row(3, "Inactive Search Target", 0.0, rating_count=1, active=0),
        ],
    )

    with application.app.test_client() as test_client:
        unfiltered = test_client.get("/")
        filtered = test_client.get("/?q=Search%20Target")

    assert unfiltered.status_code == 200
    assert filtered.status_code == 200
    assert_homepage_average(unfiltered.get_data(as_text=True), 3.0)

    filtered_html = filtered.get_data(as_text=True)
    assert "Search Target" in filtered_html
    assert "Unmatched Active Place" not in filtered_html
    assert "Inactive Search Target" not in filtered_html
    assert_homepage_average(filtered_html, 3.0)


def test_inactive_places_cannot_be_viewed_or_rated_by_visitors(
    tmp_path, monkeypatch, application
):
    db_path = configure_custom_db(
        tmp_path,
        monkeypatch,
        application,
        [
            place_row(1, "Visible Library", 4.0, rating_count=1, active=1),
            place_row(2, "Inactive Hideout", 2.0, rating_count=1, active=0),
        ],
    )

    with application.app.test_client() as test_client:
        detail = test_client.get("/place/2")
        detail_html = detail.get_data(as_text=True)
        assert not (detail.status_code == 200 and "Inactive Hideout" in detail_html)
        assert "Rate this place" not in detail_html

        response = test_client.post("/place/2/rate", data={"rating": "5"})
        assert response.status_code >= 400

    assert_rating_state(db_path, 2, 2.0, 1)
