"""Sandboxed renders in a worker process: `SandboxLimits(timeout=..., max_memory=...)`."""

import time

import pytest

import tplx
from tplx import Loader, SandboxError, SandboxLimits, TemplateNotFound, UndefinedError
from tplx import _isolate

ISOLATED = SandboxLimits(timeout=30)

#: Past the in-process bounds, so only the worker's memory limit can stop it.
MEMORY = SandboxLimits(max_output=10**12, max_memory=200 * 2**20)


def _double(value):
    return value * 2


def test_an_isolated_loader_evaluates_and_renders_in_the_worker(tree):
    tree.write("p.shtpl", "%{A}-%{G}")
    loader = Loader([tree.root], globals={"g": 1}, sandbox=ISOLATED)
    assert loader.eval("${A}-${G}", {"a": 2}) == "2-1"
    assert loader.render("p", {"a": 2}) == "2-1"
    assert tplx.eval("${A}", {"a": 3}, sandbox=ISOLATED) == "3"


def test_errors_cross_back_as_they_were_raised(tree):
    loader = Loader([tree.root], sandbox=ISOLATED)
    with pytest.raises(TemplateNotFound) as found:
        loader.render(["nope", "nada"])
    assert found.value.names == ("nope", "nada")
    with pytest.raises(UndefinedError):
        loader.eval("${MISSING}")


def test_plain_text_never_reaches_the_worker(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("the worker was asked")

    monkeypatch.setattr(_isolate, "call", refuse)
    loader = Loader([], sandbox=ISOLATED)
    assert loader.eval("web01.lan", {"a": 1}) == "web01.lan"
    assert loader.eval(80) == 80


def test_a_function_crosses_by_reference_and_a_lambda_is_refused():
    pytest.importorskip("jinja2")
    loader = Loader([], sandbox=ISOLATED)
    assert loader.eval("{{ f(2) }}", {"f": _double}, engine="jinja") == 4
    with pytest.raises(SandboxError, match="cannot cross"):
        loader.eval("{{ f(2) }}", {"f": lambda value: value}, engine="jinja")
    with pytest.raises(SandboxError, match="cannot cross"):
        Loader([], globals={"f": lambda: 1}, sandbox=ISOLATED).eval("${A}", {"a": 1})


def test_a_render_past_the_timeout_stops_and_the_next_one_runs():
    pytest.importorskip("jinja2")
    # A worker started for a longer timeout must not serve this one.
    assert Loader([], sandbox=ISOLATED).eval("{{ 1 }}", engine="jinja") == 1
    loader = Loader([], sandbox=SandboxLimits(timeout=2))
    endless = "{% for i in range(100000) %}{% for j in range(100000) %}{% endfor %}{% endfor %}"
    started = time.monotonic()
    with pytest.raises(SandboxError, match="timeout"):
        loader.eval(endless + "x", engine="jinja")
    assert time.monotonic() - started < 20
    assert loader.eval("{{ 2 + 2 }}", engine="jinja") == 4


def test_a_render_past_max_memory_stops_and_the_next_one_runs():
    pytest.importorskip("jinja2")
    loader = Loader([], sandbox=MEMORY)
    with pytest.raises(SandboxError, match="max_memory"):
        loader.eval('{{ ("x" * 400000000) | length }}', engine="jinja")
    assert loader.eval("{{ 2 + 2 }}", engine="jinja") == 4


@pytest.mark.parametrize("field", ["timeout", "max_memory"])
@pytest.mark.parametrize("value", [0, -1])
def test_a_hard_limit_must_be_positive(field, value):
    with pytest.raises(ValueError, match=field):
        SandboxLimits(**{field: value})
