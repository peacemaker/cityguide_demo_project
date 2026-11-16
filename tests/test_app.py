import re
import sqlite3
from html import unescape
from urllib.parse import urljoin, urlparse

import pytest


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def client(db_path, monkeypatch):
    import app as application

    monkeypatch.setattr(application, "DB_PATH", db_path)
    application.init_db()

    application.app.config["TESTING"] = True
    with application.app.test_client() as client:
        yield client


def _get_attr(tag, name):
    quoted = re.search(rf"\b{name}\s*=\s*(['\"])(.*?)\1", tag, flags=re.IGNORECASE | re.DOTALL)
    if quoted:
        return unescape(quoted.group(2))

    unquoted = re.search(rf"\b{name}\s*=\s*([^\s>]+)", tag, flags=re.IGNORECASE)
    if unquoted:
        return unescape(unquoted.group(1))

    return None


def _normalise_form_action(action, place_path):
    if not action or action == "#":
        return place_path

    resolved = urljoin(place_path, action)
    parsed = urlparse(resolved)
    path = parsed.path or place_path
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return path


def _find_review_form(html, place_path="/place/1"):
    forms = re.findall(r"<form\b[^>]*>.*?</form>", html, flags=re.IGNORECASE | re.DOTALL)
    for form_html in forms:
        textarea_match = re.search(r"<textarea\b[^>]*>", form_html, flags=re.IGNORECASE)
        if not textarea_match:
            continue

        form_tag = re.match(r"<form\b[^>]*>", form_html, flags=re.IGNORECASE | re.DOTALL).group(0)
        textarea_tag = textarea_match.group(0)
        field_name = _get_attr(textarea_tag, "name")

        return {
            "html": form_html,
            "method": (_get_attr(form_tag, "method") or "get").lower(),
            "action": _normalise_form_action(_get_attr(form_tag, "action"), place_path),
            "field_name": field_name,
            "textarea_tag": textarea_tag,
            "required": re.search(r"\brequired\b", textarea_tag, flags=re.IGNORECASE) is not None,
        }

    raise AssertionError("Expected the active place page to contain a review form with a textarea")


def _review_form_for(client, place_id=1):
    response = client.get(f"/place/{place_id}")
    assert response.status_code == 200
    return _find_review_form(response.get_data(as_text=True), f"/place/{place_id}")


def _submit_review(client, place_id, body, follow_redirects=False):
    form = _review_form_for(client, place_id)
    assert form["method"] == "post"
    assert form["field_name"], "Review textarea must have a name so it can be submitted"
    return client.post(
        form["action"],
        data={form["field_name"]: body},
        follow_redirects=follow_redirects,
    )


def _review_count(db_path, where_clause="", params=()):
    with sqlite3.connect(db_path) as conn:
        query = "SELECT COUNT(*) FROM reviews"
        if where_clause:
            query = f"{query} WHERE {where_clause}"
        return conn.execute(query, params).fetchone()[0]


def test_homepage(client):
    """AC-10: The homepage continues to list active places and working detail links."""
    response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Old Town Square" in html
    assert "Riverside Park" in html
    assert "Hidden Gallery" not in html
    assert "/place/1" in html

    details_response = client.get("/place/1")
    assert details_response.status_code == 200
    assert "Old Town Square" in details_response.get_data(as_text=True)


def test_place_details(client):
    """AC-10: Existing active place details remain visible after adding reviews."""
    response = client.get("/place/1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Old Town Square" in html
    assert "Historic" in html
    assert "A lively historic square" in html
    assert "Kyiv" in html
    assert "Open for discovery" in html


def test_place_page_shows_reviews_section_empty_state_and_form(client):
    """AC-01, AC-02: Active place pages expose readable reviews UI and an anonymous form."""
    response = client.get("/place/1")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    lower_html = html.lower()

    assert "reviews" in lower_html
    assert "old town square" in lower_html
    assert "no reviews" in lower_html or "be the first" in lower_html

    form = _find_review_form(html, "/place/1")
    assert form["method"] == "post"
    assert form["field_name"], "The review textarea must be a submittable field"
    assert form["required"], "The written review textarea must be required"
    assert re.search(r"<button\b|<input\b[^>]*\btype\s*=\s*(['\"]?)submit\1", form["html"], flags=re.IGNORECASE)


def test_submit_review_persists_and_renders_after_redirect_and_reload(client):
    """AC-03, AC-04: A valid review is accepted, visible, and persists on later requests."""
    review_text = "A welcoming square with great evening atmosphere."

    submit_response = _submit_review(client, 1, review_text)

    assert submit_response.status_code < 500
    assert submit_response.status_code not in {400, 404, 422}
    if 300 <= submit_response.status_code < 400:
        assert "/place/1" in submit_response.headers["Location"]
    else:
        submit_html = submit_response.get_data(as_text=True)
        assert "Old Town Square" in submit_html
        assert review_text in submit_html

    reloaded_response = client.get("/place/1")
    assert reloaded_response.status_code == 200
    assert review_text in reloaded_response.get_data(as_text=True)

    later_response = client.get("/place/1")
    assert later_response.status_code == 200
    assert review_text in later_response.get_data(as_text=True)


def test_reviews_are_scoped_to_each_place(client):
    """AC-05: Reviews submitted for one place are not displayed on another place."""
    square_review = "Square-only review from a visitor."
    park_review = "Park-only review from a visitor."

    assert _submit_review(client, 1, square_review).status_code < 500
    assert _submit_review(client, 2, park_review).status_code < 500

    square_page = client.get("/place/1").get_data(as_text=True)
    park_page = client.get("/place/2").get_data(as_text=True)

    assert square_review in square_page
    assert park_review not in square_page
    assert park_review in park_page
    assert square_review not in park_page


def test_multiple_reviews_for_same_place_are_displayed(client):
    """AC-06: Submitting another review does not overwrite earlier reviews."""
    first_review = "First visitor perspective for this place."
    second_review = "Second visitor perspective for this place."

    assert _submit_review(client, 1, first_review).status_code < 500
    assert _submit_review(client, 1, second_review).status_code < 500

    response = client.get("/place/1")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert first_review in html
    assert second_review in html


def test_blank_and_whitespace_reviews_are_rejected_with_feedback(client, db_path):
    """AC-07: Empty and whitespace-only review submissions are rejected and not saved."""
    for invalid_body in ("", "   \n\t   "):
        response = _submit_review(client, 1, invalid_body, follow_redirects=True)

        assert response.status_code < 500
        assert response.status_code in {200, 400, 422}
        html = response.get_data(as_text=True).lower()
        assert "review" in html
        assert any(word in html for word in ("please", "required", "enter", "empty", "blank"))

    assert _review_count(db_path) == 0
    page_after_rejections = client.get("/place/1").get_data(as_text=True)
    assert "No reviews" in page_after_rejections or "Be the first" in page_after_rejections


def test_inactive_or_missing_places_do_not_show_or_accept_reviews(client, db_path):
    """AC-08: Inactive and nonexistent places cannot display or accept valid reviews."""
    active_form = _review_form_for(client, 1)
    review_field = active_form["field_name"] or "review"

    for place_id in (5, 999):
        get_response = client.get(f"/place/{place_id}")
        assert get_response.status_code < 500
        assert get_response.status_code in {400, 403, 404, 405}
        assert "Leave a review" not in get_response.get_data(as_text=True)

        attempted_review = f"This invalid place review must not be created: {place_id}"
        post_response = client.post(
            f"/place/{place_id}",
            data={review_field: attempted_review},
            follow_redirects=True,
        )
        assert post_response.status_code < 500
        assert post_response.status_code in {400, 403, 404, 405}
        assert _review_count(db_path, "body = ?", (attempted_review,)) == 0
        assert _review_count(db_path, "place_id = ?", (place_id,)) == 0


def test_review_text_is_escaped_when_displayed(client):
    """AC-09: Visitor-supplied review HTML/script text is rendered harmlessly."""
    malicious_review = "Loved it <script>alert(1)</script> <b>bold claim</b> and would return."

    submit_response = _submit_review(client, 1, malicious_review)
    assert submit_response.status_code < 500

    response = client.get("/place/1")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    lower_html = html.lower()

    assert "Loved it" in html
    assert "would return" in html
    assert "<script" not in lower_html
    assert "</script" not in lower_html
    assert "<b>bold claim</b>" not in lower_html
