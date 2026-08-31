import importlib
import sys
import types


def load_app_without_flask(monkeypatch):
    fake_flask = types.ModuleType("flask")

    class FakeFlask:
        def __init__(self, *args, **kwargs):
            pass

        def route(self, *args, **kwargs):
            return lambda view_func: view_func

    fake_flask.Flask = FakeFlask
    fake_flask.request = types.SimpleNamespace(args={})
    fake_flask.render_template = lambda template, **context: context
    fake_flask.abort = lambda *args, **kwargs: None

    monkeypatch.setitem(sys.modules, "flask", fake_flask)
    sys.modules.pop("app", None)
    return importlib.import_module("app")


def test_search_matches_non_adjacent_words_in_place_name(tmp_path, monkeypatch):
    application = load_app_without_flask(monkeypatch)
    monkeypatch.setattr(application, "DB_PATH", tmp_path / "test.db")
    application.init_db()

    application.request.args = {"q": "Old Square"}
    context = application.index()

    place_names = [place["name"] for place in context["places"]]
    assert "Old Town Square" in place_names
