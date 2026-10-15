"""The library-backed engines: what each renders and how it treats undefined names."""

import logging
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

import tplx
from tplx import (
    CopyTemplate,
    EngineUnavailableError,
    HandlebarsTemplate,
    JinjaTemplate,
    LiquidTemplate,
    Loader,
    MakoTemplate,
    MustacheTemplate,
    UndefinedError,
)

DATA = {
    "target": SimpleNamespace(hostname="web01", _id="t1"),
    "nameservers": ["10.0.0.53", "10.0.0.54"],
}

#: engine, module, file, source, expected
CASES = [
    (JinjaTemplate, "jinja2", "b.j2", "host={{ target.hostname }}\n", "host=web01\n"),
    (MakoTemplate, "mako", "b.mako", "host=${target.hostname}\n", "host=web01\n"),
    (
        LiquidTemplate,
        "liquid",
        "b.liquid",
        "host={{ target.hostname }}\n",
        "host=web01\n",
    ),
    (
        HandlebarsTemplate,
        "pybars",
        "b.hbs",
        "host={{target.hostname}}\n",
        "host=web01\n",
    ),
    (
        MustacheTemplate,
        "chevron",
        "b.mustache",
        "host={{target.hostname}}\n",
        "host=web01\n",
    ),
]
IDS = [case[0].__name__ for case in CASES]

LOOPS = {
    JinjaTemplate: "{% for n in nameservers %}[{{ n }}]{% endfor %}",
    MakoTemplate: "% for n in nameservers:\n[${n}]\\\n% endfor\n",
    LiquidTemplate: "{% for n in nameservers %}[{{ n }}]{% endfor %}",
    HandlebarsTemplate: "{{#each nameservers}}[{{this}}]{{/each}}",
    MustacheTemplate: "{{#nameservers}}[{{.}}]{{/nameservers}}",
}


@pytest.mark.parametrize("engine, module, name, source, expected", CASES, ids=IDS)
def test_it_renders_the_data_keeping_the_trailing_newline(
    tree, engine, module, name, source, expected
):
    pytest.importorskip(module)
    tree.write(name, source)
    assert Loader([tree.root]).render(name, DATA) == expected


@pytest.mark.parametrize("engine, module, name, source, expected", CASES, ids=IDS)
def test_a_loop_over_a_list_works(tree, engine, module, name, source, expected):
    pytest.importorskip(module)
    tree.write(name, LOOPS[engine])
    assert Loader([tree.root]).render(name, DATA) == "[10.0.0.53][10.0.0.54]"


@pytest.mark.parametrize("engine, module, name, source, expected", CASES, ids=IDS)
def test_each_engine_is_ahead_of_the_fallback(engine, module, name, source, expected):
    engines = Loader([]).engines
    assert engines.index(engine) < engines.index(CopyTemplate)
    assert engine.can_process(name, "") and not engine.can_process("b.other", "")


@pytest.mark.parametrize(
    "engine, module, name, extra",
    [
        (JinjaTemplate, "jinja2", "b.j2", "tplx[jinja]"),
        (MakoTemplate, "mako.template", "b.mako", "tplx[mako]"),
        (LiquidTemplate, "liquid", "b.liquid", "tplx[liquid]"),
        (HandlebarsTemplate, "pybars", "b.hbs", "tplx[handlebars]"),
        (MustacheTemplate, "chevron", "b.mustache", "tplx[mustache]"),
        (tplx.GoTemplate, "gotpl", "b.tmpl", "tplx[go]"),
        (tplx.CheetahTemplate, "Cheetah", "b.cheetah", "tplx[cheetah]"),
    ],
)
def test_without_its_extra_the_error_names_it(
    tree, monkeypatch, engine, module, name, extra
):
    monkeypatch.setitem(sys.modules, module, None)
    tree.write(name, "x")
    with pytest.raises(EngineUnavailableError, match=re.escape(extra)):
        Loader([tree.root]).render(name)


def test_importing_tplx_imports_no_engine_library():
    code = (
        "import sys, tplx\n"
        "print(sorted(m for m in ('jinja2','mako','liquid','pybars','chevron') "
        "if m in sys.modules))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"


# -- undefined names ---------------------------------------------------------


@pytest.mark.parametrize(
    "module, name, source, debug",
    [
        ("jinja2", "u.j2", "k=[{{ nosuch }}]", "k=[{{ nosuch }}]"),
        ("liquid", "u.liquid", "k=[{{ nosuch }}]", "k=['nosuch' is undefined]"),
    ],
)
def test_jinja_and_liquid_honour_all_three_modes(tree, module, name, source, debug):
    pytest.importorskip(module)
    tree.write(name, source)
    with pytest.raises(UndefinedError, match=name) as excinfo:
        Loader([tree.root]).render(name)
    assert isinstance(excinfo.value, NameError)
    assert Loader([tree.root], undefined="lenient").render(name) == "k=[]"
    assert Loader([tree.root], undefined="debug").render(name) == debug


def test_mako_is_strict_by_default_and_names_the_variable(tree):
    pytest.importorskip("mako")
    tree.write("u.mako", "k=${kernl}")
    with pytest.raises(UndefinedError, match="kernl"):
        Loader([tree.root]).render("u.mako")


@pytest.mark.parametrize("mode", ["lenient", "debug"])
def test_mako_renders_an_undefined_name_empty_and_logs_it(tree, mode, caplog):
    pytest.importorskip("mako")
    tree.write("u.mako", "k=[${kernl}]")
    with caplog.at_level(logging.WARNING, logger="tplx"):
        assert Loader([tree.root], undefined=mode).render("u.mako") == "k=[]"
    assert "kernl" in caplog.text


def test_mako_drops_a_reserved_name_with_a_warning(caplog):
    pytest.importorskip("mako")
    with caplog.at_level(logging.WARNING, logger="tplx"):
        assert MakoTemplate("ok ${safe}").render(next="x", safe="kept") == "ok kept"
    assert "next" in caplog.text and "reserved" in caplog.text


@pytest.mark.parametrize(
    "module, name", [("pybars", "u.hbs"), ("chevron", "u.mustache")]
)
@pytest.mark.parametrize("mode", ["strict", "lenient", "debug"])
def test_the_logic_less_engines_always_render_an_undefined_name_empty(
    tree, module, name, mode
):
    pytest.importorskip(module)
    tree.write(name, "k=[{{ nosuch }}]")
    assert Loader([tree.root], undefined=mode).render(name) == "k=[]"


@pytest.mark.parametrize(
    "module, name, source, expected",
    [
        ("pybars", "e.hbs", "{{v}}|{{{v}}}", "a&amp;b|a&b"),
        ("chevron", "e.mustache", "{{v}}|{{{v}}}|{{& v}}", "a&amp;b|a&b|a&b"),
        ("jinja2", "e.j2", "{{ v }}", "a&b"),
        ("mako", "e.mako", "${v}", "a&b"),
        ("liquid", "e.liquid", "{{ v }}", "a&b"),
    ],
)
def test_each_engine_keeps_its_own_escaping(tree, module, name, source, expected):
    pytest.importorskip(module)
    tree.write(name, source)
    assert Loader([tree.root]).render(name, v="a&b") == expected


def test_the_package_root_exports_every_shipped_engine():
    names = {cls.__name__ for cls in tplx.registered_engines()}
    assert names <= set(tplx.__all__)


def test_mustache_writes_nothing_to_stderr_for_an_undefined_name(tree, capsys):
    pytest.importorskip("chevron")
    tree.write("w.mustache", "[{{missing}}]")
    assert Loader([tree.root]).render("w.mustache") == "[]"
    assert capsys.readouterr().err == ""


def test_liquid_templates_see_only_the_encoded_data(tree):
    pytest.importorskip("liquid")
    tree.write("v.liquid", "[{{ __tplx_values__ }}]")
    assert Loader([tree.root], undefined="lenient").render("v.liquid", x=1) == "[]"


def test_a_template_built_directly_raises_an_engine_failure_as_render_error():
    pytest.importorskip("mako")
    with pytest.raises(tplx.RenderError) as excinfo:
        MakoTemplate("${x.y}").render(x=1)
    assert isinstance(excinfo.value.__cause__, AttributeError)
