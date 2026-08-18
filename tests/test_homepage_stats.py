import importlib
import sys
import types
from pathlib import Path

import pytest


def import_app_without_real_flask(monkeypatch):
    fake_flask = types.ModuleType("flask")

    class FakeFlask:
        def __init__(self, *args, **kwargs):
            self.config = {}

        def route(self, *args, **kwargs):
            def decorator(view):
                return view

            return decorator

    fake_flask.Flask = FakeFlask
    fake_flask.request = types.SimpleNamespace(args={})
    fake_flask.render_template = lambda template, **context: context
    fake_flask.abort = lambda *args, **kwargs: None

    monkeypatch.setitem(sys.modules, "flask", fake_flask)
    sys.modules.pop("app", None)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    return importlib.import_module("app")


@pytest.fixture
def application(tmp_path, monkeypatch):
    application = import_app_without_real_flask(monkeypatch)
    monkeypatch.setattr(application, "DB_PATH", tmp_path / "test.db")
    application.init_db()
    return application


def test_homepage_statistics_match_active_visible_places(application, monkeypatch):
    monkeypatch.setattr(application.request, "args", {})

    context = application.index()

    assert len(context["places"]) == 4
    assert all(place["active"] == 1 for place in context["places"])
    assert context["total_places"] == 4
    assert context["average_rating"] == 4.5
