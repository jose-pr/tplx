"""The sandboxed loader, `evaluate`, `references` and `compile`."""

import importlib.util
import pathlib

import pytest

import tplx
from tplx import (
    Loader,
    RenderError,
    SandboxError,
    UndefinedError,
)

CTX = {"a": {"b": 21}, "xs": [3, 1, 2], "n": 2}


def _has(module):
    return importlib.util.find_spec(module) is not None


# -- the sandbox ------------------------------------------------------------------


def test_a_file_of_an_engine_that_runs_code_is_refused_before_it_is_read(
    tree, monkeypatch
):
    tree.write("app.mako", "${x}")
    tree.write("app2.erb", "<%= 1 %>")
    tree.write("app3.cheetah", "$x")
    read = []
    real = pathlib.Path.read_bytes
    monkeypatch.setattr(
        pathlib.Path, "read_bytes", lambda self: read.append(self.name) or real(self)
    )
    loader = Loader([tree.root], sandbox=True)
    for name in ("app", "app2", "app3"):
        with pytest.raises(SandboxError, match="cannot run in a sandbox"):
            loader.render(name, x=1)
    assert read == []


def test_an_include_of_such_a_file_is_refused_too(tree):
    pytest.importorskip("jinja2")
    tree.write("app.mako", "${x}")
    tree.write("page.j2", '{% include "app" %}')
    with pytest.raises(SandboxError):
        Loader([tree.root], sandbox=True).render("page", x=1)


def test_jinja_in_a_sandbox_refuses_unsafe_attributes(tree):
    pytest.importorskip("jinja2")
    ssti = "{{ ''.__class__.__mro__[1].__subclasses__() | length }}"
    tree.write("page.j2", ssti)
    assert int(Loader([tree.root]).render("page")) > 0  # trusted: Jinja as is
    with pytest.raises(SandboxError, match="unsafe"):
        Loader([tree.root], sandbox=True).render("page")
    with pytest.raises(SandboxError):
        tplx.evaluate("''.__class__.__mro__", engine="jinja", sandbox=True)


def test_go_in_a_sandbox_never_calls_a_method(tree):
    pytest.importorskip("gotpl")
    calls = []

    class Box:
        name = "box"

        def wipe(self, what="all"):
            calls.append(what)
            return "wiped"

    tree.write("page.tmpl", '{{ .o.name }}{{ .o.wipe "disk" }}')
    assert Loader([tree.root]).render("page", o=Box()) == "boxwiped"
    with pytest.raises(RenderError):
        Loader([tree.root], sandbox=True).render("page", o=Box())
    assert calls == ["disk"]  # only the trusted render called it


@pytest.mark.parametrize(
    "module, name, source, expected",
    [
        ("liquid", "p.liquid", "{{ a.b }}", "21"),
        ("chevron", "p.mustache", "{{a.b}}", "21"),
        ("pybars", "p.hbs", "{{a.b}}", "21"),
        (None, "p.shtpl", "%{A_B}", "21"),
        (None, "p.envsubst", "${A_B}", "21"),
        (None, "p.txt", "plain", b"plain"),
    ],
)
def test_sandboxed_engines_render(tree, module, name, source, expected):
    if module:
        pytest.importorskip(module)
    tree.write(name, source)
    assert Loader([tree.root], sandbox=True).render(name, CTX) == expected


# -- evaluate -------------------------------------------------------------------------


def test_python_is_the_default_engine_and_keeps_types():
    assert tplx.evaluate("a['b'] * 2 + len(xs)", CTX) == 45
    assert tplx.evaluate("[x * n for x in sorted(xs)]", CTX) == [2, 4, 6]
    with pytest.raises(UndefinedError):
        tplx.evaluate("nope + 1", CTX)


def test_a_sandbox_refuses_python():
    with pytest.raises(SandboxError, match="Python"):
        tplx.evaluate("1 + 1", sandbox=True)
    with pytest.raises(SandboxError):
        Loader([], sandbox=True).evaluate("1")


def test_default_engine_can_be_set(monkeypatch):
    pytest.importorskip("jinja2")
    monkeypatch.setattr(tplx, "DEFAULT_ENGINE", "jinja")
    assert tplx.evaluate("xs | sort", CTX) == [1, 2, 3]


def test_an_engine_is_a_class_a_name_or_a_suffix():
    pytest.importorskip("jinja2")
    for engine in (tplx.JinjaTemplate, "jinja", "j2", ".jinja2"):
        assert tplx.evaluate("a.b * n", CTX, engine=engine) == 42
    with pytest.raises(ValueError, match="no engine is named"):
        tplx.evaluate("1", engine="nosuch")


@pytest.mark.parametrize(
    "module, engine, expression, expected",
    [
        ("jinja2", "jinja", "a.b * 2", 42),
        ("liquid", "liquid", "xs | sort", [1, 2, 3]),
        ("gotpl", "go", '(index .a "b")', 21),
        ("pybars", "handlebars", "xs", [3, 1, 2]),
        ("chevron", "mustache", "a.b", 21),
        ("mako", "mako", "sorted(xs)", [1, 2, 3]),
        ("Cheetah", "cheetah", "$a.b * $n", 42),
        (None, "shell", "XS_0", "3"),
    ],
)
def test_each_engine_evaluates_in_its_own_syntax(module, engine, expression, expected):
    if module:
        pytest.importorskip(module)
    assert tplx.evaluate(expression, CTX, engine=engine) == expected


def test_an_engine_without_expressions_says_so():
    with pytest.raises(NotImplementedError, match="ERBTemplate"):
        tplx.evaluate("1", engine="erb")


def test_evaluate_sees_the_loaders_globals_and_mode():
    loader = Loader([], globals={"g": 10}, undefined="lenient")
    assert loader.evaluate("g + n", CTX) == 12
    if _has("jinja2"):
        assert loader.evaluate("missing", engine="jinja") is None


# -- references and compile -----------------------------------------------------------


@pytest.mark.parametrize(
    "module, engine, source, expected",
    [
        ("jinja2", "jinja", "{{ a }}{% set b = 1 %}{{ b }}{{ c.d }}", {"a", "c"}),
        ("liquid", "liquid", "{{ a.b }}{% assign c = 1 %}{{ c }}", {"a"}),
        ("chevron", "mustache", "{{a}}{{#s}}{{x}}{{/s}}", {"a", "s"}),
        (None, "shell", "%{A} %{B:-%{C}} %%{D}", {"A", "B", "C"}),
        (None, "envsubst", "$A ${B} $$", {"A", "B"}),
    ],
)
def test_references_are_the_top_level_names_read(module, engine, source, expected):
    if module:
        pytest.importorskip(module)
    assert Loader([]).compile(source, engine=engine).references() == expected


def test_compile_caches_by_engine_and_source():
    loader = Loader([])
    first = loader.compile("%{A}", engine="shell")
    assert loader.compile("%{A}", engine="shell") is first
    assert loader.compile("%{B}", engine="shell") is not first
    assert first.render(a=1) == "1"


def test_compile_needs_a_template_engine_and_honours_the_sandbox():
    with pytest.raises(ValueError, match="python"):
        Loader([]).compile("x")
    if _has("mako"):
        with pytest.raises(SandboxError):
            Loader([], sandbox=True).compile("${x}", engine="mako")


# -- what a sandboxed template sees of the caller's data ------------------------------


class _Recorder:
    """An object whose method records each call, so a test sees if one ran."""

    def __init__(self):
        self.name = "rec"
        self.calls = []

    def touch(self, *args):
        self.calls.append(args)
        return "touched"


@pytest.mark.parametrize(
    "module, name, source",
    [
        ("jinja2", "p.j2", "{{ o.name }}{% if o.touch %}{{ o.touch() }}{% endif %}"),
        ("liquid", "p.liquid", "{{ o.name }}{{ o.touch }}"),
        ("chevron", "p.mustache", "{{o.name}}{{#o.touch}}x{{/o.touch}}"),
        ("pybars", "p.hbs", "{{o.name}}{{o.touch}}"),
    ],
)
def test_a_sandboxed_template_never_calls_a_method_of_the_data(
    tree, module, name, source
):
    pytest.importorskip(module)
    recorder = _Recorder()
    tree.write(name, source)
    rendered = Loader([tree.root], sandbox=True, undefined="lenient").render(
        name, o=recorder
    )
    assert rendered.startswith("rec")
    assert recorder.calls == []


def test_in_a_sandbox_a_rich_value_is_its_text_and_a_given_function_still_works(tree):
    pytest.importorskip("jinja2")
    tree.write("p.j2", "{{ where }}|{{ where.name is defined }}|{{ shout('a') }}")
    loader = Loader([tree.root], sandbox=True, globals={"shout": str.upper})
    rendered = loader.render("p", where=pathlib.PurePosixPath("/srv/tftp"))
    assert rendered == "/srv/tftp|False|A"


# -- what a sandboxed render may cost ------------------------------------------------

from tplx import SandboxLimits  # noqa: E402

SMALL = SandboxLimits(max_output=1000, max_iterations=10, max_depth=5)


def test_sandbox_true_means_the_default_limits():
    assert Loader([], sandbox=True).limits == SandboxLimits()
    assert Loader([]).limits is None and Loader([], sandbox=SMALL).sandbox


@pytest.mark.parametrize(
    "module, name, source",
    [
        ("jinja2", "p.j2", "{% for i in range(5000) %}0123456789{% endfor %}"),
        ("liquid", "p.liquid", "{% for i in (1..5000) %}0123456789{% endfor %}"),
        ("gotpl", "p.tmpl", "{{range .many}}0123456789{{end}}"),
        ("chevron", "p.mustache", "{{#many}}0123456789{{/many}}"),
        (None, "p.shtpl", "%{BIG}"),
    ],
)
def test_a_render_over_its_limits_raises(tree, module, name, source):
    if module:
        pytest.importorskip(module)
    tree.write(name, source)
    data = {"many": list(range(5000)), "big": "x" * 5000}
    assert Loader([tree.root], sandbox=True).render(name, data)  # within defaults
    with pytest.raises(SandboxError):
        Loader([tree.root], sandbox=SMALL).render(name, data)


def test_an_include_cycle_across_engines_stops_at_max_depth(tree):
    pytest.importorskip("jinja2")
    pytest.importorskip("liquid")
    tree.write("a.j2", '{% include "b" %}')
    tree.write("b.liquid", "{% include 'a' %}")
    with pytest.raises(SandboxError, match="deeper than 5"):
        Loader([tree.root], sandbox=SMALL).render("a")


def test_in_a_sandbox_a_class_or_a_callable_object_cannot_be_called(tree):
    pytest.importorskip("jinja2")

    class Callable:
        def __call__(self):
            return "called"

        def __str__(self):
            return "callable-object"

    tree.write("p.j2", "{{ cls is callable }}|{{ obj is callable }}|{{ obj }}")
    rendered = Loader([tree.root], sandbox=True).render(
        "p", cls=pathlib.PurePosixPath, obj=Callable()
    )
    assert rendered == "False|False|callable-object"


def test_the_capture_hook_is_inert_outside_an_evaluation(tree):
    pytest.importorskip("liquid")
    tree.write("p.liquid", "[{{ 'x' | tplx_capture }}]")
    assert Loader([tree.root], sandbox=True).render("p") == "[]"
