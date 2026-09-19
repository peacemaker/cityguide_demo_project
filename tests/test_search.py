import importlib
import sys
import types

import pytest


@pytest.fixture
def application(tmp_path, monkeypatch):
    fake_flask = types.ModuleType("flask")

    class FakeFlask:
        def __init__(self, *args, **kwargs):
            pass

        def route(self, *args, **kwargs):
            return lambda view_func: view_func

    fake_flask.Flask = FakeFlask
    fake_flask.render_template = lambda template, **context: context
    fake_flask.request = types.SimpleNamespace(args={})
    fake_flask.abort = lambda *args, **kwargs: None

    monkeypatch.setitem(sys.modules, "flask", fake_flask)
    sys.modules.pop("app", None)
    app_module = importlib.import_module("app")

    monkeypatch.setattr(app_module, "DB_PATH", tmp_path / "test.db")
    app_module.init_db()
    return app_module


class QueryArgs:
    def __init__(self, q):
        self.q = q

    def get(self, key, default=""):
        return self.q if key == "q" else default


def place_names_for_query(app_module, query):
    app_module.request = types.SimpleNamespace(args=QueryArgs(query))
    context = app_module.index()
    return [place["name"] for place in context["places"]]


def test_search_matches_non_adjacent_words_in_place_name(application):
    assert "Old Town Square" in place_names_for_query(application, "Old Town")

    assert "Old Town Square" in place_names_for_query(application, "Old Square")
