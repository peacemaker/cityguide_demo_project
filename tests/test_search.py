import sys
import types

import pytest


class DummyFlask:
    def __init__(self, name):
        self.name = name
        self.config = {}

    def route(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator


def import_app_without_real_flask(monkeypatch):
    fake_request = types.SimpleNamespace(args={})
    fake_flask = types.ModuleType("flask")
    fake_flask.Flask = DummyFlask
    fake_flask.request = fake_request
    fake_flask.abort = lambda *args, **kwargs: None
    fake_flask.render_template = lambda template, **context: context

    monkeypatch.setitem(sys.modules, "flask", fake_flask)
    sys.modules.pop("app", None)

    import app as application

    return application


@pytest.fixture
def application(tmp_path, monkeypatch):
    app_module = import_app_without_real_flask(monkeypatch)
    monkeypatch.setattr(app_module, "DB_PATH", tmp_path / "test.db")
    app_module.init_db()
    return app_module


def test_search_matches_non_adjacent_words_in_place_name(application):
    application.request.args = {"q": "Old Square"}

    context = application.index()
    place_names = [place["name"] for place in context["places"]]

    assert "Old Town Square" in place_names
