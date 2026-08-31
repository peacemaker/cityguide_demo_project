import importlib
import sys
import types

import pytest


class _FakeFlaskApp:
    def __init__(self, *args, **kwargs):
        self.config = {}

    def route(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator


def _render_template_context(_template_name, **context):
    return context


@pytest.fixture
def application(tmp_path, monkeypatch):
    fake_flask = types.SimpleNamespace(
        Flask=_FakeFlaskApp,
        render_template=_render_template_context,
        request=types.SimpleNamespace(args={}),
        abort=lambda *args, **kwargs: None,
    )
    monkeypatch.setitem(sys.modules, "flask", fake_flask)
    sys.modules.pop("app", None)

    app_module = importlib.import_module("app")
    monkeypatch.setattr(app_module, "DB_PATH", tmp_path / "test.db")
    app_module.init_db()
    return app_module


def test_multi_word_search_matches_terms_not_contiguous_phrase(application):
    application.request.args = {"q": "Old Square"}

    context = application.index()

    place_names = [place["name"] for place in context["places"]]
    assert "Old Town Square" in place_names
