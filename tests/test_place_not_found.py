import importlib.util
import sys
import types
from pathlib import Path

import pytest


APP_PATH = Path(__file__).resolve().parents[1] / "src" / "app.py"


@pytest.fixture
def application(tmp_path, monkeypatch):
    fake_flask = types.ModuleType("flask")

    class FakeFlask:
        def __init__(self, *args, **kwargs):
            self.routes = []

        def route(self, *args, **kwargs):
            def decorator(func):
                self.routes.append((args, kwargs, func))
                return func

            return decorator

        def run(self, *args, **kwargs):
            pass

    class FakeAbort(Exception):
        def __init__(self, code):
            super().__init__(code)
            self.code = code

    def fake_abort(code):
        raise FakeAbort(code)

    def fake_render_template(template_name, **context):
        return ("rendered-template", template_name, context)

    fake_flask.Flask = FakeFlask
    fake_flask.abort = fake_abort
    fake_flask.render_template = fake_render_template
    fake_flask.request = types.SimpleNamespace(args={})
    monkeypatch.setitem(sys.modules, "flask", fake_flask)

    module_name = "cityguide_app_under_test"
    spec = importlib.util.spec_from_file_location(module_name, APP_PATH)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "DB_PATH", tmp_path / "test.db")
    module.init_db()

    return module, FakeAbort


def _is_404_response(result):
    if not isinstance(result, tuple) or len(result) < 2:
        return False
    status = result[1]
    if status == 404:
        return True
    return isinstance(status, str) and status.startswith("404")


def test_missing_place_returns_404_instead_of_rendering_none(application):
    app_module, FakeAbort = application

    try:
        result = app_module.place_details(999)
    except FakeAbort as exc:
        assert exc.code == 404
        return

    assert _is_404_response(result), (
        "Expected missing place id to return or abort with 404; "
        f"instead the route returned {result!r}"
    )
