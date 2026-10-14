"""Includes resolve through the lookup that loaded the including file."""

import pytest

from tplx import Loader, NoEngineError, TemplateNotFound, UndefinedError


def _needs(module, extra):
    return pytest.importorskip(module, reason=f"needs the '{extra}' extra")


def test_jinja_include_and_extends(tree):
    _needs("jinja2", "jinja")
    tree.write("head.j2", "head {{ x }}\n")
    tree.write("base.j2", "[{% block body %}{% endblock %}]")
    tree.write("page.j2", '{% include "head" %}body')
    tree.write(
        "kid.j2", '{% extends "base" %}{% block body %}kid {{ x }}{% endblock %}'
    )
    loader = Loader([tree.root])
    assert loader.render("page.j2", x=1) == "head 1\nbody"
    assert loader.render("kid.j2", x=2) == "[kid 2]"


def test_mako_include_and_inherit(tree):
    _needs("mako", "mako")
    tree.write("head.mako", "head ${x}")
    tree.write("base.mako", "[${next.body()}]")
    tree.write("page.mako", "<%include file='head'/> body")
    tree.write("kid.mako", "<%inherit file='base'/>kid ${x}")
    loader = Loader([tree.root])
    assert loader.render("page.mako", x=1) == "head 1 body"
    assert loader.render("kid.mako", x=2) == "[kid 2]"


def test_a_missing_include_is_template_not_found(tree):
    _needs("jinja2", "jinja")
    _needs("mako", "mako")
    _needs("liquid", "liquid")
    tree.write("a.j2", '{% include "nope" %}')
    tree.write("b.mako", "<%include file='nope'/>")
    tree.write("c.liquid", "{% include 'nope' %}")
    loader = Loader([tree.root])
    for name in ("a.j2", "b.mako", "c.liquid"):
        with pytest.raises(TemplateNotFound, match="nope"):
            loader.render(name)


def test_mako_names_are_root_relative(tree):
    _needs("mako", "mako")
    tree.write("head.mako", "root head")
    tree.write("sub/page.mako", "<%include file='head'/>")
    assert Loader([tree.root]).render("sub/page.mako") == "root head"


def test_liquid_include_and_render(tree):
    _needs("liquid", "liquid")
    tree.write("head.liquid", "head {{ x }}")
    tree.write("page.liquid", "{% include 'head' %} {% render 'head', x: 9 %}")
    assert Loader([tree.root]).render("page.liquid", x=1) == "head 1 head 9"


def test_handlebars_partials(tree):
    _needs("pybars", "handlebars")
    tree.write("head.hbs", "head {{x}}")
    tree.write("page.hbs", "{{> head}} body")
    assert Loader([tree.root]).render("page.hbs", x=1) == "head 1 body"


def test_mustache_partials(tree):
    _needs("chevron", "mustache")
    tree.write("head.mustache", "head {{x}}")
    tree.write("page.mustache", "{{> head}} body")
    assert Loader([tree.root]).render("page.mustache", x=1) == "head 1 body"


def test_a_missing_mustache_partial_raises_only_when_strict(tree):
    _needs("chevron", "mustache")
    tree.write("page.mustache", "[{{> nope}}]")
    with pytest.raises(TemplateNotFound):
        Loader([tree.root]).render("page.mustache")
    assert Loader([tree.root], undefined="lenient").render("page.mustache") == "[]"


def test_an_include_goes_through_the_candidates(tree):
    _needs("jinja2", "jinja")
    tree.write("web01.head.j2", "web01 head")
    tree.write("head.j2", "generic head")
    tree.write("page.j2", '{% include "head" %}')
    loader = Loader([tree.root])

    def web01(name):
        return [f"web01.{name}", name]

    assert loader.render("page.j2", candidates=web01) == "web01 head"
    assert loader.render("page.j2") == "generic head"


def test_an_include_goes_through_the_paths(tree):
    _needs("jinja2", "jinja")
    tree.write("debian/head.j2", "debian head")
    tree.write("head.j2", "generic head")
    tree.write("page.j2", '{% include "head" %}')
    assert Loader([tree.root]).render("page.j2", paths=["debian"]) == "debian head"


def test_an_include_resolves_to_the_file_a_render_would(tree):
    # Lowest stem match whatever its engine, as for a render: head.j2 < head.mako.
    _needs("jinja2", "jinja")
    _needs("mako", "mako")
    tree.write("head.mako", "mako ${x}")
    tree.write("page.j2", '{% include "head" %}')
    loader = Loader([tree.root])
    assert loader.render("page.j2", x=1) == "mako 1"
    tree.write("head.j2", "jinja {{ x }}")
    assert Loader([tree.root]).render("page.j2", x=1) == "jinja 1"


def test_a_shell_file_included_from_jinja_is_rendered_by_the_shell_engine(tree):
    _needs("jinja2", "jinja")
    tree.write("net.shtpl", "IP=%{TARGET_IP}")
    tree.write("page.j2", '[{% include "net" %}]')
    data = {"target": {"ip": "10.0.0.5"}}
    assert Loader([tree.root]).render("page.j2", data) == "[IP=10.0.0.5]"


def test_a_jinja_loop_variable_reaches_the_included_engine(tree):
    _needs("jinja2", "jinja")
    tree.write("line.shtpl", "ns %{NS}\n")
    tree.write("page.j2", '{% for ns in servers %}{% include "line" %}{% endfor %}')
    rendered = Loader([tree.root]).render("page.j2", servers=["a", "b"])
    assert rendered == "ns a\nns b\n"


def test_an_unclaimed_file_is_included_as_it_is(tree):
    _needs("jinja2", "jinja")
    tree.write("motd.txt", "hello {{ x }}")
    tree.write("page.j2", '{% include "motd.txt" %}')
    assert Loader([tree.root]).render("page.j2", x=1) == "hello {{ x }}"


def test_mako_includes_another_engines_file(tree):
    _needs("mako", "mako")
    tree.write("net.shtpl", "IP=%{IP}")
    tree.write("page.mako", "[<%include file='net'/>]")
    assert Loader([tree.root]).render("page.mako", ip="10.0.0.5") == "[IP=10.0.0.5]"


def test_liquid_includes_another_engines_file_as_text(tree):
    _needs("liquid", "liquid")
    tree.write("net.shtpl", "IP=%{IP} {{ not liquid }} {% endraw %}")
    tree.write("page.liquid", "[{% include 'net' %}][{% render 'net' %}]")
    expected = "IP=10.0.0.5 {{ not liquid }} {% endraw %}"
    rendered = Loader([tree.root]).render("page.liquid", ip="10.0.0.5")
    assert rendered == f"[{expected}][{expected}]"


def test_handlebars_includes_another_engines_file(tree):
    _needs("pybars", "handlebars")
    tree.write("net.shtpl", "IP=%{IP} {{raw}}")
    tree.write("page.hbs", "[{{> net}}]")
    assert (
        Loader([tree.root]).render("page.hbs", ip="1.2.3.4") == "[IP=1.2.3.4 {{raw}}]"
    )


def test_mustache_includes_another_engines_file(tree):
    _needs("chevron", "mustache")
    tree.write("net.shtpl", "IP=%{IP} {{raw}}")
    tree.write("page.mustache", "[{{> net}}] {{ip}}")
    assert (
        Loader([tree.root]).render("page.mustache", ip="1.2.3.4")
        == "[IP=1.2.3.4 {{raw}}] 1.2.3.4"
    )


def test_an_included_engines_strict_mode_applies(tree):
    _needs("jinja2", "jinja")
    tree.write("net.shtpl", "IP=%{IP}")
    tree.write("page.j2", '{% include "net" %}')
    with pytest.raises(UndefinedError, match="IP"):
        Loader([tree.root]).render("page.j2")
    assert Loader([tree.root], undefined="lenient").render("page.j2") == "IP="


def test_bytes_that_are_not_text_cannot_be_included(tree):
    _needs("jinja2", "jinja")
    tree.write("blob.bin", b"\xff\xfe")
    tree.write("page.j2", '{% include "blob.bin" %}')
    with pytest.raises(NoEngineError, match="not UTF-8"):
        Loader([tree.root]).render("page.j2")


@pytest.mark.parametrize("name", ["../secret", "..\\\\secret", "C:/secret"])
def test_an_include_cannot_escape_the_roots(tree, name):
    _needs("jinja2", "jinja")
    tree.write("page.j2", '{%% include "%s" %%}' % name)
    with pytest.raises(TemplateNotFound, match="escapes"):
        Loader([tree.root]).render("page.j2")


def test_a_missing_handlebars_partial_raises_only_when_strict(tree):
    _needs("pybars", "handlebars")
    tree.write("page.hbs", "[{{> nope}}]")
    with pytest.raises(TemplateNotFound):
        Loader([tree.root]).render("page.hbs")
    assert Loader([tree.root], undefined="lenient").render("page.hbs") == "[]"


@pytest.mark.parametrize(
    "module, extra, page",
    [("pybars", "handlebars", "page.hbs"), ("chevron", "mustache", "page.mustache")],
)
def test_a_partial_is_found_once_and_another_engines_output_follows_the_data(
    tree, monkeypatch, module, extra, page
):
    _needs(module, extra)
    suffix = page.rsplit(".", 1)[1]
    tree.write(f"part.{suffix}", "p{{x}}")
    tree.write("net.shtpl", "n%{X}")
    tree.write(page, "{{> part}}|{{> net}}")
    lookup = Loader([tree.root]).lookup()
    calls = []
    real = type(lookup).include
    monkeypatch.setattr(
        type(lookup), "include", lambda self, *a: calls.append(a[0]) or real(self, *a)
    )
    assert lookup.render(page, x=1) == "p1|n1"
    assert lookup.render(page, x=2) == "p2|n2"
    assert calls.count("part") == 1
