import re
import sqlite3
from collections import Counter
from html.parser import HTMLParser

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


class _InputCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs = []

    def handle_starttag(self, tag, attrs):
        if tag == "input":
            self.inputs.append(dict(attrs))


def _app_module():
    import app as application

    return application


def _html(response):
    return response.get_data(as_text=True)


def _rating_inputs(markup):
    parser = _InputCollector()
    parser.feed(markup)
    return [attrs for attrs in parser.inputs if attrs.get("name") == "rating"]


def _connect_db():
    application = _app_module()
    return sqlite3.connect(application.DB_PATH)


def _insert_rating(place_id, rating):
    with _connect_db() as conn:
        conn.execute(
            "INSERT INTO place_ratings (place_id, rating) VALUES (?, ?)",
            (place_id, rating),
        )
        conn.commit()


def _ratings_for_place(place_id):
    with _connect_db() as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT rating FROM place_ratings WHERE place_id = ? ORDER BY id",
                (place_id,),
            ).fetchall()
        ]


def _aggregate_for_place(place_id):
    with _connect_db() as conn:
        return conn.execute(
            "SELECT ROUND(AVG(rating), 1), COUNT(*) FROM place_ratings WHERE place_id = ?",
            (place_id,),
        ).fetchone()


def _assert_rating_summary(markup, average, count):
    if count == 0:
        assert "0 ratings" in markup
        assert "No ratings yet" in markup
        return

    assert f"{average:.1f}" in markup
    count_text = f"{count} {'rating' if count == 1 else 'ratings'}"
    assert count_text in markup


def _card_for_place(markup, place_name):
    cards = re.findall(
        r"<article\b[^>]*class=[\"'][^\"']*card[^\"']*[\"'][^>]*>(.*?)</article>",
        markup,
        flags=re.DOTALL,
    )
    for card in cards:
        if place_name in card:
            return card
    raise AssertionError(f"No place card found for {place_name!r}")


def test_place_detail_shows_five_star_rating_control_and_rating_summary(client):
    _insert_rating(1, 4)

    response = client.get("/place/1")

    assert response.status_code == 200
    markup = _html(response)
    inputs = _rating_inputs(markup)
    values = Counter(input_attrs.get("value") for input_attrs in inputs)

    assert values == Counter({"1": 1, "2": 1, "3": 1, "4": 1, "5": 1})
    assert all(input_attrs.get("type") == "radio" for input_attrs in inputs)
    assert "Submit rating" in markup
    _assert_rating_summary(markup, 4.0, 1)


def test_anonymous_visitor_can_submit_valid_rating(client):
    response = client.post("/place/1/ratings", data={"rating": "5"})

    assert response.status_code in {302, 303}
    assert "/place/1" in response.headers["Location"]
    assert _ratings_for_place(1) == [5]

    detail_response = client.get("/place/1")
    assert detail_response.status_code == 200
    _assert_rating_summary(_html(detail_response), 5.0, 1)


def test_invalid_rating_submissions_are_rejected_without_changing_aggregate(client):
    _insert_rating(1, 4)
    invalid_submissions = [
        ("missing", {}),
        ("non_numeric", {"rating": "five"}),
        ("fractional", {"rating": "3.5"}),
        ("below_range", {"rating": "0"}),
        ("above_range", {"rating": "6"}),
    ]

    for label, form_data in invalid_submissions:
        response = client.post("/place/1/ratings", data=form_data)

        assert response.status_code == 400, label
        assert _ratings_for_place(1) == [4], label
        _assert_rating_summary(_html(response), 4.0, 1)

    detail_response = client.get("/place/1")
    _assert_rating_summary(_html(detail_response), 4.0, 1)


def test_average_rating_and_count_are_calculated_from_accepted_ratings(client):
    for rating in [2, 4, 5]:
        _insert_rating(1, rating)

    response = client.get("/place/1")

    assert response.status_code == 200
    assert _aggregate_for_place(1) == (3.7, 3)
    _assert_rating_summary(_html(response), 3.7, 3)


def test_browse_page_shows_rating_summary_for_default_and_search_results(client):
    _insert_rating(1, 5)
    _insert_rating(1, 3)
    _insert_rating(3, 2)

    response = client.get("/")

    assert response.status_code == 200
    markup = _html(response)
    _assert_rating_summary(_card_for_place(markup, "Old Town Square"), 4.0, 2)
    _assert_rating_summary(_card_for_place(markup, "Science Museum"), 2.0, 1)
    _assert_rating_summary(_card_for_place(markup, "Riverside Park"), None, 0)
    _assert_rating_summary(_card_for_place(markup, "Central Market"), None, 0)

    search_response = client.get("/", query_string={"q": "Science"})

    assert search_response.status_code == 200
    search_markup = _html(search_response)
    _assert_rating_summary(_card_for_place(search_markup, "Science Museum"), 2.0, 1)
    assert "Old Town Square" not in search_markup


def test_rating_submission_updates_detail_and_browse_pages(client):
    _insert_rating(2, 5)

    response = client.post(
        "/place/2/ratings",
        data={"rating": "3"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    _assert_rating_summary(_html(response), 4.0, 2)

    detail_response = client.get("/place/2")
    assert detail_response.status_code == 200
    _assert_rating_summary(_html(detail_response), 4.0, 2)

    browse_response = client.get("/")
    assert browse_response.status_code == 200
    _assert_rating_summary(_card_for_place(_html(browse_response), "Riverside Park"), 4.0, 2)


def test_ratings_are_isolated_per_place(client):
    _insert_rating(2, 2)

    client.post("/place/1/ratings", data={"rating": "5"})
    client.post("/place/1/ratings", data={"rating": "4"})

    assert _aggregate_for_place(1) == (4.5, 2)
    assert _aggregate_for_place(2) == (2.0, 1)

    place_one_response = client.get("/place/1")
    place_two_response = client.get("/place/2")
    browse_response = client.get("/")

    assert place_one_response.status_code == 200
    assert place_two_response.status_code == 200
    assert browse_response.status_code == 200
    _assert_rating_summary(_html(place_one_response), 4.5, 2)
    _assert_rating_summary(_html(place_two_response), 2.0, 1)

    browse_markup = _html(browse_response)
    _assert_rating_summary(_card_for_place(browse_markup, "Old Town Square"), 4.5, 2)
    _assert_rating_summary(_card_for_place(browse_markup, "Riverside Park"), 2.0, 1)


def test_rating_data_persists_across_later_requests(client):
    response = client.post("/place/4/ratings", data={"rating": "5"})

    assert response.status_code in {302, 303}
    assert _ratings_for_place(4) == [5]

    application = _app_module()
    with application.app.test_client() as later_client:
        detail_response = later_client.get("/place/4")
        browse_response = later_client.get("/")

    assert detail_response.status_code == 200
    assert browse_response.status_code == 200
    _assert_rating_summary(_html(detail_response), 5.0, 1)
    _assert_rating_summary(_card_for_place(_html(browse_response), "Central Market"), 5.0, 1)
