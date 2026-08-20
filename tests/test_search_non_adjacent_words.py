import importlib
import sys
import types

import pytest


class DummyFlask:
    def __init__(self, *args, **kwargs):
        self.config = {}

    def route(self, *args, **kwargs):
        def decorator(function):
            return function

        return decorator


def import_app_without_flask(monkeypatch):
    fake_flask = types.ModuleType("flask")
    fake_flask.Flask = DummyFlask
    fake_flask.request = types.SimpleNamespace(args={})
    fake_flask.render_template = lambda template, **context: context
    fake_flask.abort = lambda *args, **kwargs: None

    monkeypatch.setitem(sys.modules, "flask", fake_flask)
    monkeypatch.delitem(sys.modules, "app", raising=False)

    return importlib.import_module("app")


@pytest.fixture
def application(tmp_path, monkeypatch):
    application = import_app_without_flask(monkeypatch)
    monkeypatch.setattr(application, "DB_PATH", tmp_path / "test.db")
    application.init_db()
    return application


def test_search_matches_non_adjacent_words_in_place_name(application):
    application.request.args = {"q": "Old Square"}

    context = application.index()
    place_names = [place["name"] for place in context["places"]]

    assert "Old Town Square" in place_names
