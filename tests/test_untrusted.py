"""The sandboxed loader, `eval`, `references` and `compile`."""

import importlib.util
import pathlib
import re

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
        tplx.eval("{{ ''.__class__.__mro__ }}", engine="jinja", sandbox=True)


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


# -- eval -----------------------------------------------------------------------------


def test_the_default_engine_is_the_shell_syntax_with_a_dollar():
    assert tplx.DEFAULT_ENGINE is tplx.DollarTemplate
    assert tplx.eval("${A_B}", CTX) == "21"
    url = "http://${HOST:-localhost}:${PORT}/"
    assert tplx.eval(url, {"port": 80}) == "http://localhost:80/"
    assert tplx.eval("cost $5, $HOME", CTX) == "cost $5, $HOME"
    with pytest.raises(UndefinedError):
        tplx.eval("${NOPE}", CTX)


def test_the_default_runs_in_a_sandbox_and_can_be_set(monkeypatch):
    assert tplx.eval("${N}", CTX, sandbox=True) == "2"
    pytest.importorskip("jinja2")
    monkeypatch.setattr(tplx, "DEFAULT_ENGINE", "jinja")
    assert tplx.eval("{{ xs | sort }}", CTX) == [1, 2, 3]


def test_an_engine_is_a_class_a_name_or_a_suffix():
    pytest.importorskip("jinja2")
    for engine in (tplx.JinjaTemplate, "jinja", "j2", ".jinja2"):
        assert tplx.eval("{{ a.b * n }}", CTX, engine=engine) == 42
    for name in ("nosuch", "python"):
        with pytest.raises(ValueError, match="no engine is named"):
            tplx.eval("{{ 1 }}", engine=name)


@pytest.mark.parametrize(
    "module, engine, template, expected",
    [
        ("jinja2", "jinja", "{{ a.b * 2 }}", 42),
        ("liquid", "liquid", "{{ xs | sort }}", [1, 2, 3]),
        ("gotpl", "go", '{{ index .a "b" }}', 21),
        ("pybars", "handlebars", "{{xs}}", [3, 1, 2]),
        ("chevron", "mustache", "{{a.b}}", 21),
        ("mako", "mako", "${sorted(xs)}", [1, 2, 3]),
        ("Cheetah", "cheetah", "$a.b", 21),
        (None, "shell", "%{XS_0}", "3"),
    ],
)
def test_each_engine_evaluates_one_expression_in_its_own_syntax(
    module, engine, template, expected
):
    if module:
        pytest.importorskip(module)
    assert tplx.eval(template, CTX, engine=engine) == expected


def test_an_engine_without_expressions_renders_the_template():
    class Upper(tplx.Template):
        _SYNTAX = re.compile("<")
        _EXPRESSION = ("<", ">", "", "")

        def render_values(self, values):
            return self.source.upper()

    assert tplx.eval("<x>", engine=Upper) == "<X>"
    assert tplx.eval("plain", engine=Upper) == "plain"
    with pytest.raises(NotImplementedError):
        tplx.ERBTemplate._evaluate_expression("1", {})


def test_the_engine_class_decides_without_a_loader():
    assert tplx.DollarTemplate.eval("${A}-${B}", {"a": 1, "b": 2}) == "1-2"
    assert tplx.DollarTemplate.eval("no syntax", {}) == "no syntax"
    if _has("jinja2"):
        assert tplx.JinjaTemplate.eval("{{ x + 1 }}", {"x": 1}) == 2
        assert tplx.JinjaTemplate.eval("x={{ x }}", {"x": 1}) == "x=1"


def test_eval_sees_the_loaders_globals_and_mode():
    loader = Loader([], globals={"g": 10}, undefined="lenient")
    assert loader.eval("${G}-${N}", CTX) == "10-2"
    if _has("jinja2"):
        assert loader.eval("{{ g + n }}", CTX, engine="jinja") == 12
        assert loader.eval("{{ missing }}", engine="jinja") is None


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


def test_compile_uses_the_default_engine_and_honours_the_sandbox():
    assert Loader([]).compile("${X}").render(x=1) == "1"
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


@pytest.mark.parametrize(
    "module, engine, sandbox",
    [
        ("jinja2", "jinja", True),
        ("liquid", "liquid", False),
        ("liquid", "liquid", True),
    ],
)
def test_shared_and_cyclic_lists_cost_one_visit(module, engine, sandbox):
    pytest.importorskip(module)
    shared = [1]
    for _ in range(40):
        shared = [shared, shared]
    loop = [1]
    loop.append(loop)
    loader = Loader([], sandbox=sandbox)
    assert loader.eval("{{ 1 }}", {"big": shared, "loop": loop}, engine=engine) == 1


# -- a sandbox refuses before it allocates past max_output --------------------------

TIGHT = SandboxLimits(max_output=1000)


@pytest.mark.parametrize(
    "expression",
    [
        '"x" * 5000',
        "[0] * 5000",
        "9 ** 5000",
        '"x".center(5000)',
        '"x".ljust(5000)',
        '"{:>5000}".format(1)',
        '"{:>{}}".format(1, 5000)',
        '"%5000d" % 1',
        '"x" | center(5000)',
        '"%5000d" | format(1)',
        '"a" | replace("", "x" * 900)',
        'range(10) | join("x" * 900)',
        '"a\nb\nc" | indent(900)',
        "lipsum(1000)",
        '("x" * 600) ~ ("y" * 600)',
        '("x" * 600) + ("y" * 600)',
    ],
)
def test_jinja_refuses_a_value_past_the_limit_before_building_it(expression):
    pytest.importorskip("jinja2")
    with pytest.raises(SandboxError, match="larger than the sandbox allows"):
        Loader([], sandbox=TIGHT).eval("{{ " + expression + " }}", engine="jinja")


def test_a_value_grown_step_by_step_in_a_loop_stops_at_the_limit(tree):
    pytest.importorskip("jinja2")
    tree.write(
        "p.j2",
        '{% set ns = namespace(a="x") %}'
        "{% for i in range(40) %}{% set ns.a = ns.a ~ ns.a %}{% endfor %}"
        "{{ ns.a | length }}",
    )
    with pytest.raises(SandboxError):
        Loader([tree.root], sandbox=TIGHT).render("p")


def test_ordinary_sandboxed_expressions_still_work():
    pytest.importorskip("jinja2")
    loader = Loader([], sandbox=TIGHT)
    assert (
        loader.eval('{{ "ab" * 3 ~ "{:>4}".format(1) }}', engine="jinja")
        == "ababab   1"
    )
    assert loader.eval("{{ 2 ** 100 }}", engine="jinja") == 2**100


def test_go_printf_refuses_a_width_past_the_limit():
    pytest.importorskip("gotpl")
    loader = Loader([], sandbox=TIGHT)
    assert loader.eval('{{ printf "%5d" 1 }}', engine="go") == "    1"
    with pytest.raises(SandboxError):
        loader.eval('{{ printf "%5000d" 1 }}', engine="go")


def test_liquid_replace_and_join_refuse_a_result_past_the_limit():
    pytest.importorskip("liquid")
    loader = Loader([], sandbox=TIGHT)
    with pytest.raises(SandboxError):
        loader.eval(
            '{{ "aaaaaaaaaa" | replace: "a", s }}', {"s": "x" * 500}, engine="liquid"
        )
    with pytest.raises(SandboxError):
        loader.eval(
            "{{ xs | join: s }}",
            {"xs": list(range(10)), "s": "x" * 500},
            engine="liquid",
        )


def test_shell_replacement_stops_at_the_limit():
    loader = Loader([], sandbox=TIGHT)
    data = {"v": "a" * 100}
    assert loader.eval("%{V//a/bb}", data, engine="shell") == "b" * 200
    with pytest.raises(SandboxError):
        loader.eval("%{V//a/" + "b" * 50 + "}", data, engine="shell")


def test_an_evaluated_value_past_the_limit_is_refused():
    with pytest.raises(SandboxError):
        Loader([], sandbox=TIGHT).eval(
            "{{xs}}", {"xs": list(range(5000))}, engine="mustache"
        )


# -- is_template, and what eval does with a template ----------------------------------

PLAIN_TEXT = ["web01.lan", "cost $5 per month", "100% done", "/srv/tftp"]


@pytest.mark.parametrize(
    "engine, templated",
    [
        (tplx.JinjaTemplate, ["{{ p }}", "{% if x %}y{% endif %}", "{# note #}"]),
        (tplx.LiquidTemplate, ["{{ p }}", "{% if x %}y{% endif %}"]),
        (tplx.GoTemplate, ["{{.p}}"]),
        (tplx.MustacheTemplate, ["{{p}}"]),
        (tplx.MakoTemplate, ["${p}", "<%include file='x'/>", "% if x:\n"]),
        (tplx.CheetahTemplate, ["$p", "${p}", "#if $x"]),
        (tplx.ERBTemplate, ["<%= p %>"]),
        (tplx.EnvsubstTemplate, ["$P", "${P}"]),
        (tplx.ShellTemplate, ["%{P}"]),
        (tplx.DollarTemplate, ["${P}", "${P:-x}"]),
    ],
)
def test_is_template_finds_syntax_and_passes_plain_text(engine, templated):
    for text in templated:
        assert engine.is_template(text), text
    for text in PLAIN_TEXT:
        assert not engine.is_template(text), text


def test_is_template_follows_a_subclass_delimiter_and_copy_has_none():
    class Dollar(tplx.ShellTemplate):
        DELIMITER = "$"

    class Square(tplx.GoTemplate):
        DELIMITERS = ("[[", "]]")

    assert Dollar.is_template("${A}") and not Dollar.is_template("%{A}")
    assert Square.is_template("[[.x]]") and not Square.is_template("{{.x}}")
    assert not tplx.CopyTemplate.is_template("{{ anything }}")
    assert tplx.Template.is_template("plain")  # unknown: every text may hold some


@pytest.mark.parametrize(
    "module, engine, value, expected",
    [
        ("jinja2", "jinja", "{{ port + 1 }}", 81),
        ("jinja2", "jinja", " {{- xs | sort -}} ", [1, 3]),
        ("jinja2", "jinja", "Test {{ host }}", "Test web01"),
        ("jinja2", "jinja", "{% if port > 1 %}big{% endif %}", "big"),
        ("liquid", "liquid", "{{ xs | sort }}", [1, 3]),
        ("gotpl", "go", "{{ .port }}", 80),
        ("chevron", "mustache", "{{port}}", 80),
        ("chevron", "mustache", "{{{host}}}", "web01"),
        ("mako", "mako", "${port * 2}", 160),
        ("Cheetah", "cheetah", "$port", 80),
        (None, "envsubst", "${HOST}:${PORT}", "web01:80"),
    ],
)
def test_eval_keeps_one_expressions_type_and_renders_the_rest(
    module, engine, value, expected
):
    if module:
        pytest.importorskip(module)
    context = {"port": 80, "host": "web01", "xs": [3, 1]}
    assert tplx.eval(value, context, engine=engine) == expected


def test_eval_returns_plain_values_as_they_are(monkeypatch):
    compiled = []
    real = tplx.Lookup.compile
    monkeypatch.setattr(
        tplx.Lookup,
        "compile",
        lambda self, *a, **k: compiled.append(a) or real(self, *a, **k),
    )
    for value in (80, None, ["{{ x }}"], "web01.lan", "cost $5"):
        assert tplx.eval(value, engine="shell") is value
    assert compiled == []


def test_eval_honours_the_sandbox():
    pytest.importorskip("jinja2")
    assert tplx.eval("{{ p * 2 }}", {"p": 4}, engine="jinja", sandbox=True) == 8
    with pytest.raises(SandboxError):
        tplx.eval('{{ "x" * 5000000 }}', engine="jinja", sandbox=True)
    with pytest.raises(SandboxError):
        tplx.eval("${p}", {"p": 1}, engine="mako", sandbox=True)
