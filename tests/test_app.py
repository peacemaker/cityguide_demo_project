import re
from html.parser import HTMLParser

import pytest


VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
RATING_SUMMARY_RE = re.compile(
    r"(?:★\s*)?(?P<average>\d+(?:\.\d+)?)\s*(?:/5|stars?)?\s*"
    r"\(\s*(?P<count>\d+)\s+ratings?\s*\)",
    re.IGNORECASE,
)
ZERO_RATING_RE = re.compile(r"(no ratings? yet|not rated yet|no rating yet)", re.IGNORECASE)


@pytest.fixture
def client(tmp_path, monkeypatch):
    import app as application

    db = tmp_path / "test.db"
    monkeypatch.setattr(application, "DB_PATH", db)
    application.init_db()

    application.app.config["TESTING"] = True
    with application.app.test_client() as client:
        yield client


class ClassTextExtractor(HTMLParser):
    def __init__(self, tag, class_name):
        super().__init__(convert_charrefs=True)
        self.tag = tag
        self.class_name = class_name
        self.depth = 0
        self.current = []
        self.texts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()

        if self.depth == 0 and tag == self.tag and self.class_name in classes:
            self.depth = 1
            self.current = []
            return

        if self.depth and tag not in VOID_TAGS:
            self.depth += 1

    def handle_endtag(self, tag):
        if not self.depth or tag in VOID_TAGS:
            return

        self.depth -= 1
        if self.depth == 0:
            self.texts.append(normalize_text(" ".join(self.current)))
            self.current = []

    def handle_data(self, data):
        if self.depth:
            self.current.append(data)


class RatingFormParser(HTMLParser):
    def __init__(self, action):
        super().__init__(convert_charrefs=True)
        self.action = action
        self.in_form = False
        self.depth = 0
        self.form_seen = False
        self.radio_names = []
        self.radio_values = []
        self.has_submit_button = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)

        if not self.in_form:
            if (
                tag == "form"
                and attrs.get("action") == self.action
                and attrs.get("method", "get").lower() == "post"
            ):
                self.in_form = True
                self.form_seen = True
                self.depth = 1
            return

        if tag == "input" and attrs.get("type", "").lower() == "radio":
            self.radio_names.append(attrs.get("name"))
            self.radio_values.append(attrs.get("value"))

        if tag == "button" and attrs.get("type", "submit").lower() == "submit":
            self.has_submit_button = True

        if tag not in VOID_TAGS:
            self.depth += 1

    def handle_endtag(self, tag):
        if not self.in_form or tag in VOID_TAGS:
            return

        self.depth -= 1
        if self.depth == 0:
            self.in_form = False


def normalize_text(value):
    return " ".join(value.split())


def response_text(response):
    return normalize_text(response.get_data(as_text=True))


def extract_class_texts(html, tag, class_name):
    parser = ClassTextExtractor(tag, class_name)
    parser.feed(html)
    return parser.texts


def detail_text(response):
    details = extract_class_texts(response.get_data(as_text=True), "article", "detail")
    assert len(details) == 1, "Expected exactly one place detail article"
    return details[0]


def place_card_text(response, place_name):
    cards = extract_class_texts(response.get_data(as_text=True), "article", "card")
    matches = [card for card in cards if place_name in card]
    assert len(matches) == 1, f"Expected exactly one homepage card for {place_name!r}"
    return matches[0]


def assert_zero_rating_state(text):
    normalized = normalize_text(text)
    assert "0 ratings" in normalized
    assert ZERO_RATING_RE.search(normalized), f"Missing clear zero-rating state in: {normalized}"


def assert_rating_aggregate(text, expected_average, expected_count):
    normalized = normalize_text(text)

    if expected_count == 0:
        assert_zero_rating_state(normalized)
        return (None, 0)

    matches = [
        match for match in RATING_SUMMARY_RE.finditer(normalized)
        if int(match.group("count")) == expected_count
    ]
    assert matches, f"Missing rating summary with {expected_count} ratings in: {normalized}"

    displayed_average = matches[0].group("average")
    decimal_places = len(displayed_average.partition(".")[2])
    assert float(displayed_average) == pytest.approx(round(expected_average, decimal_places))
    return (displayed_average, expected_count)


def submitted_ratings_for(place_id):
    import app as application

    conn = application.get_db()
    try:
        rows = conn.execute(
            "SELECT rating FROM place_ratings WHERE place_id = ? ORDER BY id",
            (place_id,),
        ).fetchall()
    finally:
        conn.close()
    return [row["rating"] for row in rows]


def submit_rating(client, place_id, rating):
    return client.post(
        f"/place/{place_id}/rating",
        data={"rating": str(rating)},
        follow_redirects=True,
    )


def test_homepage(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Old Town Square" in response.data


def test_place_details(client):
    response = client.get("/place/1")
    assert response.status_code == 200
    assert b"Old Town Square" in response.data


def test_place_detail_shows_five_star_rating_form(client):
    response = client.get("/place/1")
    assert response.status_code == 200

    parser = RatingFormParser(action="/place/1/rating")
    parser.feed(response.get_data(as_text=True))

    assert parser.form_seen, "The detail page must provide a POST form for rating this place"
    assert len(parser.radio_values) == 5
    assert set(parser.radio_values) == {"1", "2", "3", "4", "5"}
    assert all(name == "rating" for name in parser.radio_names)
    assert parser.has_submit_button

    page_text = response_text(response)
    assert "Rate this place" in page_text
    assert "Submit rating" in page_text


def test_submit_rating_updates_detail_average_count_and_confirmation(client):
    response = submit_rating(client, place_id=1, rating=4)
    assert response.status_code == 200

    page_text = response_text(response).lower()
    assert any(word in page_text for word in ("thank", "recorded", "submitted", "success"))
    assert "Old Town Square" in response_text(response)
    assert_rating_aggregate(detail_text(response), expected_average=4, expected_count=1)
    assert submitted_ratings_for(1) == [4]

    reloaded = client.get("/place/1")
    assert reloaded.status_code == 200
    assert_rating_aggregate(detail_text(reloaded), expected_average=4, expected_count=1)


def test_invalid_ratings_are_rejected_without_changing_aggregates(client):
    invalid_submissions = [
        ("missing", {}),
        ("zero", {"rating": "0"}),
        ("above scale", {"rating": "6"}),
        ("non-numeric", {"rating": "abc"}),
    ]

    for label, payload in invalid_submissions:
        response = client.post("/place/1/rating", data=payload)
        assert response.status_code == 400, label
        assert "rating" in response_text(response).lower(), label
        assert submitted_ratings_for(1) == [], label

        reloaded = client.get("/place/1")
        assert reloaded.status_code == 200
        assert_rating_aggregate(detail_text(reloaded), expected_average=0, expected_count=0)


def test_homepage_shows_rating_summary_for_each_active_place(client):
    response = submit_rating(client, place_id=2, rating=5)
    assert response.status_code == 200

    homepage = client.get("/")
    assert homepage.status_code == 200
    homepage_text = response_text(homepage)
    assert "Hidden Gallery" not in homepage_text

    expected_cards = {
        "Old Town Square": (0, 0),
        "Riverside Park": (5, 1),
        "Science Museum": (0, 0),
        "Central Market": (0, 0),
    }
    for place_name, (expected_average, expected_count) in expected_cards.items():
        card = place_card_text(homepage, place_name)
        assert "rating" in card.lower()
        assert_rating_aggregate(card, expected_average, expected_count)


def test_unrated_places_show_clear_zero_rating_state(client):
    detail = client.get("/place/3")
    assert detail.status_code == 200
    science_detail = detail_text(detail)
    assert_rating_aggregate(science_detail, expected_average=0, expected_count=0)
    assert "4.7" not in science_detail, "Legacy seeded rating must not be shown as a submitted average"

    homepage = client.get("/")
    science_card = place_card_text(homepage, "Science Museum")
    assert_rating_aggregate(science_card, expected_average=0, expected_count=0)
    assert "4.7" not in science_card, "Legacy seeded rating must not be shown as a submitted average"


def test_multiple_ratings_average_consistently_on_listing_and_detail(client):
    for rating in (2, 4, 5):
        response = submit_rating(client, place_id=1, rating=rating)
        assert response.status_code == 200

    expected_average = (2 + 4 + 5) / 3

    detail = client.get("/place/1")
    assert detail.status_code == 200
    detail_summary = assert_rating_aggregate(
        detail_text(detail),
        expected_average=expected_average,
        expected_count=3,
    )

    homepage = client.get("/")
    assert homepage.status_code == 200
    listing_summary = assert_rating_aggregate(
        place_card_text(homepage, "Old Town Square"),
        expected_average=expected_average,
        expected_count=3,
    )

    assert listing_summary == detail_summary


def test_ratings_are_isolated_per_place(client):
    response = submit_rating(client, place_id=1, rating=5)
    assert response.status_code == 200
    assert submitted_ratings_for(1) == [5]
    assert submitted_ratings_for(2) == []
    assert submitted_ratings_for(3) == []
    assert submitted_ratings_for(4) == []

    rated_detail = client.get("/place/1")
    assert_rating_aggregate(detail_text(rated_detail), expected_average=5, expected_count=1)

    other_places = [
        (2, "Riverside Park"),
        (3, "Science Museum"),
        (4, "Central Market"),
    ]
    for place_id, place_name in other_places:
        detail = client.get(f"/place/{place_id}")
        assert detail.status_code == 200
        assert_rating_aggregate(detail_text(detail), expected_average=0, expected_count=0)

    homepage = client.get("/")
    assert_rating_aggregate(place_card_text(homepage, "Old Town Square"), expected_average=5, expected_count=1)
    for _, place_name in other_places:
        assert_rating_aggregate(place_card_text(homepage, place_name), expected_average=0, expected_count=0)
