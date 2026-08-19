import importlib
import sys
import types
from pathlib import Path

import pytest


# Flask is not installed in this test environment, but this route-level test only
# needs app.route decorators to import the module.
flask_stub = types.ModuleType("flask")


class DummyFlask:
    def __init__(self, *args, **kwargs):
        pass

    def route(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator


flask_stub.Flask = DummyFlask
flask_stub.request = types.SimpleNamespace(args={})
flask_stub.abort = lambda code: None
flask_stub.render_template = lambda *args, **kwargs: None
sys.modules.setdefault("flask", flask_stub)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
application = importlib.import_module("app")


class NotFound(Exception):
    def __init__(self, code):
        self.code = code


def test_missing_place_aborts_404_instead_of_rendering_none(tmp_path, monkeypatch):
    monkeypatch.setattr(application, "DB_PATH", tmp_path / "test.db")
    application.init_db()

    def fake_abort(code):
        raise NotFound(code)

    def fake_render_template(template_name, **context):
        if template_name == "place.html" and context.get("place") is None:
            raise AssertionError(
                "place_details rendered place.html with place=None instead of aborting 404"
            )
        return "rendered"

    monkeypatch.setattr(application, "abort", fake_abort)
    monkeypatch.setattr(application, "render_template", fake_render_template)

    with pytest.raises(NotFound) as exc_info:
        application.place_details(99999)

    assert exc_info.value.code == 404
