import importlib
import sys
import types

import pytest


@pytest.fixture
def application(tmp_path, monkeypatch):
    class FakeFlask:
        def __init__(self, *args, **kwargs):
            pass

        def route(self, *args, **kwargs):
            return lambda view: view

    fake_flask = types.SimpleNamespace(
        Flask=FakeFlask,
        render_template=lambda template, **context: context,
        request=types.SimpleNamespace(args={}),
        abort=lambda *args, **kwargs: None,
    )
    monkeypatch.setitem(sys.modules, "flask", fake_flask)
    sys.modules.pop("app", None)

    app_module = importlib.import_module("app")
    monkeypatch.setattr(app_module, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(app_module, "render_template", lambda template, **context: context)
    app_module.init_db()
    return app_module


def test_search_matches_all_words_without_requiring_contiguous_phrase(application, monkeypatch):
    monkeypatch.setattr(
        application,
        "request",
        types.SimpleNamespace(args={"q": "Old Square"}),
    )

    context = application.index()

    assert "Old Town Square" in [place["name"] for place in context["places"]]
