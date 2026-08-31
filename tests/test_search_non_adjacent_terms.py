import sys
import types

import pytest


class _FakeFlask:
    def __init__(self, *args, **kwargs):
        self.config = {}

    def route(self, *args, **kwargs):
        def decorator(func):
            return func
        return decorator


def _import_app_without_flask(monkeypatch):
    fake_flask = types.SimpleNamespace(
        Flask=_FakeFlask,
        render_template=lambda *args, **kwargs: kwargs,
        request=types.SimpleNamespace(args={}),
        abort=lambda *args, **kwargs: None,
    )
    monkeypatch.setitem(sys.modules, "flask", fake_flask)
    sys.modules.pop("app", None)

    import app as application

    return application


@pytest.fixture
def application(tmp_path, monkeypatch):
    application = _import_app_without_flask(monkeypatch)

    db = tmp_path / "test.db"
    monkeypatch.setattr(application, "DB_PATH", db)
    application.init_db()
    monkeypatch.setattr(application, "render_template", lambda template, **context: context)

    return application


def test_search_matches_non_adjacent_words_in_place_name(application, monkeypatch):
    monkeypatch.setattr(
        application,
        "request",
        types.SimpleNamespace(args={"q": "Old Square"}),
    )

    context = application.index()

    place_names = [place["name"] for place in context["places"]]
    assert "Old Town Square" in place_names
