import importlib
import sys
import types


class DummyFlask:
    def __init__(self, *args, **kwargs):
        pass

    def route(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator


def load_app_with_fake_flask(monkeypatch, tmp_path):
    fake_request = types.SimpleNamespace(args={})

    fake_flask = types.ModuleType("flask")
    fake_flask.Flask = DummyFlask
    fake_flask.render_template = lambda template, **context: context
    fake_flask.request = fake_request
    fake_flask.abort = lambda *args, **kwargs: None

    monkeypatch.setitem(sys.modules, "flask", fake_flask)
    sys.modules.pop("app", None)
    application = importlib.import_module("app")

    monkeypatch.setattr(application, "DB_PATH", tmp_path / "test.db")
    application.init_db()
    return application, fake_request


def test_search_matches_non_contiguous_words_in_place_name(monkeypatch, tmp_path):
    application, fake_request = load_app_with_fake_flask(monkeypatch, tmp_path)
    fake_request.args = {"q": "Old Square"}

    context = application.index()

    place_names = [place["name"] for place in context["places"]]
    assert "Old Town Square" in place_names
