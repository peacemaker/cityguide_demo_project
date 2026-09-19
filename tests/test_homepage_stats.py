import importlib
import sys
import types


class DummyFlask:
    def __init__(self, *args, **kwargs):
        self.config = {}

    def route(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator


def import_app_without_real_flask(monkeypatch):
    fake_flask = types.ModuleType("flask")
    fake_flask.Flask = DummyFlask
    fake_flask.request = types.SimpleNamespace(args={})
    fake_flask.render_template = lambda template, **context: context
    fake_flask.abort = lambda *args, **kwargs: None

    monkeypatch.setitem(sys.modules, "flask", fake_flask)
    sys.modules.pop("app", None)
    return importlib.import_module("app")


def test_homepage_stats_match_visible_active_places(tmp_path, monkeypatch):
    application = import_app_without_real_flask(monkeypatch)
    monkeypatch.setattr(application, "DB_PATH", tmp_path / "test.db")
    application.init_db()

    rendered_context = application.index()
    visible_places = rendered_context["places"]
    visible_average = round(
        sum(place["rating"] for place in visible_places) / len(visible_places), 1
    )

    assert "Hidden Gallery" not in [place["name"] for place in visible_places]
    assert (rendered_context["total_places"], rendered_context["average_rating"]) == (
        len(visible_places),
        visible_average,
    )
