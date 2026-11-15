import re
import sqlite3
from html.parser import HTMLParser

import pytest


ACTIVE_PLACE_NAMES = [
    "Old Town Square",
    "Riverside Park",
    "Science Museum",
    "Central Market",
]


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    import app as application

    db = tmp_path / "test.db"
    monkeypatch.setattr(application, "DB_PATH", db)
    application.app.config.update(TESTING=True, SECRET_KEY="acceptance-test-secret")
    application.init_db()
    return application


@pytest.fixture
def client(app_module):
    with app_module.app.test_client() as client:
        yield client


@pytest.fixture
def db_path(app_module):
    return app_module.DB_PATH


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def visible_text(html):
    parser = _TextExtractor()
    parser.feed(html)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def article_texts(html):
    blocks = re.findall(r"<article\b[^>]*>(.*?)</article>", html, flags=re.IGNORECASE | re.DOTALL)
    return [visible_text(block) for block in blocks]


def assert_place_summary(html, place_name, expected_summary):
    for article in article_texts(html):
        if place_name in article:
            assert expected_summary in article
            return
    raise AssertionError(f"Could not find article for {place_name!r} in response")


class _RatingFormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_post_form = False
        self.forms = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.in_post_form = attrs.get("method", "get").lower() == "post"
            if self.in_post_form:
                self.forms.append({"attrs": attrs, "controls": []})
            return

        if self.in_post_form and self.forms and tag in {"input", "button", "select", "option"}:
            self.forms[-1]["controls"].append((tag, attrs))

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_post_form = False


def rating_form_values(html):
    parser = _RatingFormParser()
    parser.feed(html)
    values = []
    for form in parser.forms:
        values.extend(
            attrs.get("value")
            for _tag, attrs in form["controls"]
            if attrs.get("name") == "rating" and attrs.get("value") is not None
        )
    return values


def rating_stats(db_path, place_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS count, AVG(rating) AS average FROM place_ratings WHERE place_id = ?",
            (place_id,),
        ).fetchone()
        return row["count"], row["average"]
    finally:
        conn.close()


def rating_values(db_path, place_id):
    conn = sqlite3.connect(db_path)
    try:
        return [
            row[0]
            for row in conn.execute(
                "SELECT rating FROM place_ratings WHERE place_id = ? ORDER BY id",
                (place_id,),
            ).fetchall()
        ]
    finally:
        conn.close()


def test_homepage(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Old Town Square" in response.data


def test_place_details(client):
    response = client.get("/place/1")
    assert response.status_code == 200
    assert b"Old Town Square" in response.data


# AC-01: Active place detail pages expose a five-star control with values 1 through 5 and a submit action.
def test_active_place_detail_exposes_five_star_rating_form(client):
    response = client.get("/place/1")
    html = response.get_data(as_text=True)
    text = visible_text(html)

    assert response.status_code == 200
    assert "Rate this place" in text
    assert "Submit rating" in text
    assert html.count("★") >= 5
    assert set(rating_form_values(html)) == {"1", "2", "3", "4", "5"}


# AC-02: Only whole-star values 1 through 5 are accepted; invalid input leaves stored ratings unchanged.
def test_rating_validation_accepts_only_whole_star_values_and_does_not_mutate_on_invalid(client, db_path):
    assert rating_stats(db_path, 1) == (0, None)

    for valid_rating in ("1", "5"):
        response = client.post("/place/1", data={"rating": valid_rating}, follow_redirects=True)
        assert response.status_code == 200

    assert rating_values(db_path, 1) == [1, 5]
    assert rating_stats(db_path, 1) == (2, 3.0)

    invalid_payloads = [
        {},
        {"rating": ""},
        {"rating": "0"},
        {"rating": "6"},
        {"rating": "-1"},
        {"rating": "2.5"},
        {"rating": "not-a-number"},
    ]

    for payload in invalid_payloads:
        before = rating_stats(db_path, 1)
        response = client.post("/place/1", data=payload)
        assert response.status_code < 500
        assert rating_stats(db_path, 1) == before

    assert rating_values(db_path, 1) == [1, 5]


# AC-03: A submitted rating remains included after page reloads and app/database re-initialization.
def test_submitted_rating_persists_after_reload_and_app_reinitialization(client, app_module, db_path):
    response = client.post("/place/1", data={"rating": "4"}, follow_redirects=True)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Thank you" in visible_text(html)
    assert_place_summary(html, "Old Town Square", "★ 4.0 (1 rating)")
    assert rating_values(db_path, 1) == [4]

    reloaded = client.get("/place/1")
    assert_place_summary(reloaded.get_data(as_text=True), "Old Town Square", "★ 4.0 (1 rating)")

    app_module.init_db()
    with app_module.app.test_client() as restarted_client:
        restarted = restarted_client.get("/place/1")
        assert restarted.status_code == 200
        assert_place_summary(restarted.get_data(as_text=True), "Old Town Square", "★ 4.0 (1 rating)")
    assert rating_values(db_path, 1) == [4]


# AC-04: The browsing page shows every listed active place's average/count and updates after new ratings.
def test_homepage_shows_each_active_place_rating_summary_and_updates_after_rating(client):
    initial = client.get("/")
    html = initial.get_data(as_text=True)
    text = visible_text(html)

    assert initial.status_code == 200
    for place_name in ACTIVE_PLACE_NAMES:
        assert place_name in text
        assert_place_summary(html, place_name, "No ratings yet (0 ratings)")
    assert "Hidden Gallery" not in text

    client.post("/place/1", data={"rating": "5"}, follow_redirects=True)
    updated = client.get("/")
    updated_html = updated.get_data(as_text=True)

    assert updated.status_code == 200
    assert_place_summary(updated_html, "Old Town Square", "★ 5.0 (1 rating)")
    for unchanged_place in ACTIVE_PLACE_NAMES[1:]:
        assert_place_summary(updated_html, unchanged_place, "No ratings yet (0 ratings)")


# AC-05: The individual detail page shows the current average/count before and after rating submission.
def test_detail_page_shows_current_average_and_total_before_and_after_submission(client):
    initial = client.get("/place/2")
    assert initial.status_code == 200
    assert_place_summary(initial.get_data(as_text=True), "Riverside Park", "No ratings yet (0 ratings)")

    updated = client.post("/place/2", data={"rating": "1"}, follow_redirects=True)
    assert updated.status_code == 200
    assert_place_summary(updated.get_data(as_text=True), "Riverside Park", "★ 1.0 (1 rating)")


# AC-06: Rating aggregates are isolated per place on both list and detail pages.
def test_rating_aggregates_are_place_specific_on_list_and_detail_pages(client):
    client.post("/place/1", data={"rating": "5"}, follow_redirects=True)
    client.post("/place/1", data={"rating": "3"}, follow_redirects=True)
    client.post("/place/2", data={"rating": "1"}, follow_redirects=True)

    homepage = client.get("/").get_data(as_text=True)
    assert_place_summary(homepage, "Old Town Square", "★ 4.0 (2 ratings)")
    assert_place_summary(homepage, "Riverside Park", "★ 1.0 (1 rating)")
    assert_place_summary(homepage, "Science Museum", "No ratings yet (0 ratings)")

    place_one = client.get("/place/1").get_data(as_text=True)
    place_two = client.get("/place/2").get_data(as_text=True)
    place_three = client.get("/place/3").get_data(as_text=True)
    assert_place_summary(place_one, "Old Town Square", "★ 4.0 (2 ratings)")
    assert_place_summary(place_two, "Riverside Park", "★ 1.0 (1 rating)")
    assert_place_summary(place_three, "Science Museum", "No ratings yet (0 ratings)")


# AC-07: Fractional averages are consistently rounded/displayed to one decimal place on list and detail pages.
def test_fractional_averages_use_one_decimal_format_consistently(client):
    client.post("/place/4", data={"rating": "5"}, follow_redirects=True)
    client.post("/place/4", data={"rating": "4"}, follow_redirects=True)

    homepage = client.get("/").get_data(as_text=True)
    detail = client.get("/place/4").get_data(as_text=True)

    assert_place_summary(homepage, "Central Market", "★ 4.5 (2 ratings)")
    assert_place_summary(detail, "Central Market", "★ 4.5 (2 ratings)")


# AC-08: Places with zero ratings show a clear zero-state on list and detail pages.
def test_unrated_places_have_clear_zero_state_on_list_and_detail_pages(client):
    homepage = client.get("/").get_data(as_text=True)
    detail = client.get("/place/3").get_data(as_text=True)

    assert_place_summary(homepage, "Science Museum", "No ratings yet (0 ratings)")
    assert_place_summary(detail, "Science Museum", "No ratings yet (0 ratings)")


# AC-09: Successful submission gives confirmation and immediately displays the updated rating summary.
def test_valid_rating_submission_confirms_success_and_shows_updated_summary(client):
    response = client.post("/place/3", data={"rating": "5"}, follow_redirects=True)
    html = response.get_data(as_text=True)
    text = visible_text(html)

    assert response.status_code == 200
    assert "Thank you" in text or "submitted" in text
    assert_place_summary(html, "Science Museum", "★ 5.0 (1 rating)")


# AC-10: Inactive or non-existent places cannot be viewed or rated and do not create rating rows.
def test_inactive_and_missing_places_cannot_be_viewed_or_rated(client, db_path):
    homepage = client.get("/")
    assert "Hidden Gallery" not in visible_text(homepage.get_data(as_text=True))

    inactive_get = client.get("/place/5")
    missing_get = client.get("/place/999")
    assert inactive_get.status_code == 404
    assert missing_get.status_code == 404

    inactive_post = client.post("/place/5", data={"rating": "5"})
    missing_post = client.post("/place/999", data={"rating": "5"})
    assert inactive_post.status_code == 404
    assert missing_post.status_code == 404

    assert rating_stats(db_path, 5) == (0, None)
    assert rating_stats(db_path, 999) == (0, None)
