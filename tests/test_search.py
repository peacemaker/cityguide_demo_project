import importlib
import sys
import types


def load_app_without_flask(monkeypatch):
    """Import the app module with a tiny Flask stub so the view can be called directly."""

    class FakeFlask:
        def __init__(self, *_args, **_kwargs):
            pass

        def route(self, *_args, **_kwargs):
            return lambda func: func

    fake_flask = types.ModuleType("flask")
    fake_flask.Flask = FakeFlask
    fake_flask.render_template = lambda *_args, **_kwargs: None
    fake_flask.request = types.SimpleNamespace(args={})
    fake_flask.abort = lambda *args, **kwargs: None

    monkeypatch.setitem(sys.modules, "flask", fake_flask)
    sys.modules.pop("app", None)
    return importlib.import_module("app")


def test_search_matches_non_adjacent_words_in_place_name(tmp_path, monkeypatch):
    application = load_app_without_flask(monkeypatch)
    monkeypatch.setattr(application, "DB_PATH", tmp_path / "test.db")
    application.init_db()

    application.request.args = {"q": "Old Square"}
    monkeypatch.setattr(
        application,
        "render_template",
        lambda _template, **context: context,
    )

    context = application.index()
    place_names = [place["name"] for place in context["places"]]

    assert "Old Town Square" in place_names
