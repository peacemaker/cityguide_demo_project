import re
import sqlite3

import pytest

# Starter tests. The hidden bugs are intentionally not covered yet.


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    import app as application

    db = tmp_path / "test.db"
    monkeypatch.setattr(application, "DB_PATH", db)
    application.init_db()
    application.app.config["TESTING"] = True
    yield application


@pytest.fixture
def client(app_module):
    with app_module.app.test_client() as client:
        yield client


def _connect(application):
    conn = sqlite3.connect(application.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _fetch_place(application, place_id):
    conn = _connect(application)
    try:
        row = conn.execute("SELECT * FROM places WHERE id = ?", (place_id,)).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _all_places_by_id(application):
    conn = _connect(application)
    try:
        rows = conn.execute("SELECT * FROM places ORDER BY id").fetchall()
        return {row["id"]: dict(row) for row in rows}
    finally:
        conn.close()


def _active_places(application):
    conn = _connect(application)
    try:
        rows = conn.execute("SELECT * FROM places WHERE active = 1 ORDER BY id").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _active_average(application):
    conn = _connect(application)
    try:
        return conn.execute("SELECT AVG(rating) FROM places WHERE active = 1").fetchone()[0]
    finally:
        conn.close()


def _set_place(application, place_id, *, rating, rating_count, active=None):
    conn = _connect(application)
    try:
        if active is None:
            conn.execute(
                "UPDATE places SET rating = ?, rating_count = ? WHERE id = ?",
                (rating, rating_count, place_id),
            )
        else:
            conn.execute(
                "UPDATE places SET rating = ?, rating_count = ?, active = ? WHERE id = ?",
                (rating, rating_count, active, place_id),
            )
        conn.commit()
    finally:
        conn.close()


def _homepage_average_text(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    match = re.search(
        r"<strong>\s*([^<]+?)\s*</strong>\s*<span>\s*average rating\s*</span>",
        html,
        re.IGNORECASE,
    )
    assert match, "homepage must display the overall average rating statistic"
    return match.group(1).strip(), html


def _assert_place_rating_display(html, place_name, expected_rating, expected_count):
    name_index = html.find(place_name)
    assert name_index != -1, f"{place_name} should be visible in the rendered page"
    nearby = html[max(0, name_index - 500) : name_index + 900]
    assert f"{expected_rating:.1f}" in nearby
    assert f"{expected_count} rating" in nearby


def _assert_homepage_place_count(html, expected_count):
    assert re.search(
        rf"<strong>\s*{expected_count}\s*</strong>\s*<span>\s*places\s*</span>",
        html,
        re.IGNORECASE,
    ), "homepage place count should use the active visitor-visible population"


def test_homepage(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Old Town Square" in response.data


def test_place_details(client):
    response = client.get("/place/1")
    assert response.status_code == 200
    assert b"Old Town Square" in response.data


def test_seeded_places_start_with_rating_count_one_and_preserve_decimal_rating(app_module):
    expected_seed_ratings = {
        1: 4.8,
        2: 4.5,
        3: 4.7,
        4: 4.2,
        5: 4.6,
    }

    places = _all_places_by_id(app_module)

    assert set(expected_seed_ratings).issubset(places)
    for place_id, expected_rating in expected_seed_ratings.items():
        place = places[place_id]
        assert place["rating_count"] == 1
        assert place["rating"] == pytest.approx(expected_rating)


def test_valid_five_star_submissions_update_average_and_count(app_module, client):
    place_id = 1
    initial = _fetch_place(app_module, place_id)
    initial_rating = initial["rating"]
    initial_count = initial["rating_count"]

    detail_response = client.get(f"/place/{place_id}")
    assert detail_response.status_code == 200
    detail_html = detail_response.get_data(as_text=True)
    for stars in range(1, 6):
        assert f'name="rating"' in detail_html
        assert f'value="{stars}"' in detail_html

    accepted_ratings = []
    for stars in range(1, 6):
        response = client.post(
            f"/place/{place_id}/rate",
            data={"rating": str(stars)},
            follow_redirects=True,
        )
        assert response.status_code == 200
        accepted_ratings.append(stars)

        expected_count = initial_count + len(accepted_ratings)
        expected_average = (
            initial_rating * initial_count + sum(accepted_ratings)
        ) / expected_count
        updated = _fetch_place(app_module, place_id)

        assert updated["rating_count"] == expected_count
        assert updated["rating"] == pytest.approx(expected_average)


def test_invalid_rating_submissions_are_rejected_without_state_changes(app_module, client):
    place_id = 2
    invalid_payloads = [
        {},
        {"rating": ""},
        {"rating": "0"},
        {"rating": "6"},
        {"rating": "3.5"},
        {"rating": "five"},
    ]
    before_place = _fetch_place(app_module, place_id)
    before_active_average = _active_average(app_module)
    before_homepage_average, _ = _homepage_average_text(client)

    for payload in invalid_payloads:
        response = client.post(f"/place/{place_id}/rate", data=payload)
        assert response.status_code < 500

        after_place = _fetch_place(app_module, place_id)
        after_homepage_average, _ = _homepage_average_text(client)

        assert after_place["rating_count"] == before_place["rating_count"]
        assert after_place["rating"] == pytest.approx(before_place["rating"])
        assert _active_average(app_module) == pytest.approx(before_active_average)
        assert after_homepage_average == before_homepage_average


def test_browse_and_search_cards_display_current_average_and_rating_count(app_module, client):
    response = client.get("/")
    assert response.status_code == 200
    homepage_html = response.get_data(as_text=True)

    for place in _active_places(app_module):
        _assert_place_rating_display(
            homepage_html,
            place["name"],
            place["rating"],
            place["rating_count"],
        )

    search_response = client.get("/?q=Riverside")
    assert search_response.status_code == 200
    search_html = search_response.get_data(as_text=True)
    _assert_place_rating_display(search_html, "Riverside Park", 4.5, 1)

    response = client.post(
        "/place/2/rate",
        data={"rating": "5"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    updated = _fetch_place(app_module, 2)
    assert updated["rating_count"] == 2
    assert updated["rating"] == pytest.approx((4.5 + 5) / 2)

    homepage_html = client.get("/").get_data(as_text=True)
    search_html = client.get("/?q=Riverside").get_data(as_text=True)
    _assert_place_rating_display(
        homepage_html,
        "Riverside Park",
        updated["rating"],
        updated["rating_count"],
    )
    _assert_place_rating_display(
        search_html,
        "Riverside Park",
        updated["rating"],
        updated["rating_count"],
    )


def test_place_detail_displays_rating_count_and_submission_form(app_module, client):
    place_id = 3
    response = client.get(f"/place/{place_id}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    _assert_place_rating_display(html, "Science Museum", 4.7, 1)
    assert "method=\"post\"" in html.lower()
    assert f"/place/{place_id}/rate" in html
    assert 'name="rating"' in html
    for stars in range(1, 6):
        assert f'value="{stars}"' in html

    response = client.post(
        f"/place/{place_id}/rate",
        data={"rating": "3"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    updated = _fetch_place(app_module, place_id)
    assert updated["rating_count"] == 2
    assert updated["rating"] == pytest.approx((4.7 + 3) / 2)
    _assert_place_rating_display(
        response.get_data(as_text=True),
        "Science Museum",
        updated["rating"],
        updated["rating_count"],
    )

    reloaded_detail = client.get(f"/place/{place_id}").get_data(as_text=True)
    browsing_html = client.get("/").get_data(as_text=True)
    _assert_place_rating_display(
        reloaded_detail,
        "Science Museum",
        updated["rating"],
        updated["rating_count"],
    )
    _assert_place_rating_display(
        browsing_html,
        "Science Museum",
        updated["rating"],
        updated["rating_count"],
    )


def test_inactive_place_is_not_visible_accessible_or_rateable(app_module, client):
    inactive_place_id = 5
    before_hidden = _fetch_place(app_module, inactive_place_id)
    before_active_average = _active_average(app_module)
    before_homepage_average, homepage_html = _homepage_average_text(client)

    assert before_hidden["active"] == 0
    assert "Hidden Gallery" not in homepage_html
    search_response = client.get("/?q=Hidden")
    assert search_response.status_code == 200
    assert "Hidden Gallery" not in search_response.get_data(as_text=True)

    detail_response = client.get(f"/place/{inactive_place_id}")
    assert detail_response.status_code == 404

    direct_rating_response = client.post(
        f"/place/{inactive_place_id}/rate",
        data={"rating": "5"},
    )
    assert direct_rating_response.status_code < 500

    nonexistent_rating_response = client.post(
        "/place/999/rate",
        data={"rating": "5"},
    )
    assert nonexistent_rating_response.status_code < 500

    after_hidden = _fetch_place(app_module, inactive_place_id)
    after_homepage_average, _ = _homepage_average_text(client)
    assert after_hidden["rating_count"] == before_hidden["rating_count"]
    assert after_hidden["rating"] == pytest.approx(before_hidden["rating"])
    assert _active_average(app_module) == pytest.approx(before_active_average)
    assert after_homepage_average == before_homepage_average


def test_homepage_average_uses_only_active_visible_places(app_module, client):
    controlled_places = {
        1: (5.0, 1, 1),
        2: (4.0, 1, 1),
        3: (3.0, 1, 1),
        4: (2.0, 1, 1),
        5: (1.0, 1, 0),
    }
    for place_id, (rating, count, active) in controlled_places.items():
        _set_place(app_module, place_id, rating=rating, rating_count=count, active=active)

    average_text, homepage_html = _homepage_average_text(client)

    assert average_text == "3.5"
    _assert_homepage_place_count(homepage_html, 4)
    assert "Hidden Gallery" not in homepage_html
    assert client.get("/place/5").status_code == 404


def test_homepage_average_remains_unweighted_by_rating_count(app_module, client):
    weighted_trap = {
        1: (5.0, 10, 1),
        2: (1.0, 1, 1),
        3: (1.0, 1, 1),
        4: (1.0, 1, 1),
        5: (5.0, 100, 0),
    }
    for place_id, (rating, count, active) in weighted_trap.items():
        _set_place(app_module, place_id, rating=rating, rating_count=count, active=active)

    average_text, _ = _homepage_average_text(client)

    assert average_text == "2.0"
    assert average_text != "4.1"


def test_rating_submission_updates_list_detail_and_homepage_average_consistently(app_module, client):
    place_id = 2
    initial = _fetch_place(app_module, place_id)

    response = client.post(
        f"/place/{place_id}/rate",
        data={"rating": "1"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    expected_place_average = (initial["rating"] * initial["rating_count"] + 1) / (
        initial["rating_count"] + 1
    )
    expected_place_count = initial["rating_count"] + 1
    updated = _fetch_place(app_module, place_id)

    assert updated["rating"] == pytest.approx(expected_place_average)
    assert updated["rating_count"] == expected_place_count

    detail_html = client.get(f"/place/{place_id}").get_data(as_text=True)
    homepage_average, homepage_html = _homepage_average_text(client)
    expected_homepage_average = (
        _fetch_place(app_module, 1)["rating"]
        + expected_place_average
        + _fetch_place(app_module, 3)["rating"]
        + _fetch_place(app_module, 4)["rating"]
    ) / 4

    _assert_place_rating_display(
        detail_html,
        "Riverside Park",
        expected_place_average,
        expected_place_count,
    )
    _assert_place_rating_display(
        homepage_html,
        "Riverside Park",
        expected_place_average,
        expected_place_count,
    )
    assert homepage_average == f"{expected_homepage_average:.1f}"
