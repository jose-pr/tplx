"""`Loader(configure=...)`: each engine's own environment, set up by the caller."""

import pytest

from tplx import (
    HandlebarsTemplate,
    JinjaTemplate,
    LiquidTemplate,
    Loader,
    MakoTemplate,
    MustacheTemplate,
)


def _shout(value):
    return str(value).upper()


def test_a_jinja_filter_reaches_the_template_and_its_includes(tree):
    pytest.importorskip("jinja2")
    tree.write("part.j2", "{{ name | shout }}")
    tree.write("page.j2", "{{ name | shout }}/{% include 'part' %}")
    loader = Loader(
        [tree.root],
        configure={JinjaTemplate: lambda env: env.filters.update(shout=_shout)},
    )
    assert loader.render("page.j2", name="web") == "WEB/WEB"


def test_a_liquid_filter(tree):
    pytest.importorskip("liquid")
    tree.write("page.liquid", "{{ name | shout }}")
    loader = Loader(
        [tree.root],
        configure={LiquidTemplate: lambda env: env.filters.update(shout=_shout)},
    )
    assert loader.render("page.liquid", name="web") == "WEB"


def test_mako_template_args_apply_to_the_template_and_its_includes(tree):
    pytest.importorskip("mako")
    tree.write("part.mako", "${shout(name)}")
    tree.write("page.mako", "${shout(name)}/<%include file='part'/>")

    def setup(lookup):
        lookup.template_args["imports"] = [f"from {__name__} import _shout as shout"]

    loader = Loader([tree.root], configure={MakoTemplate: setup})
    assert loader.render("page.mako", name="web") == "WEB/WEB"


def test_a_handlebars_helper_reaches_the_template_and_its_partials(tree):
    pytest.importorskip("pybars")
    tree.write("part.hbs", "{{shout name}}")
    tree.write("page.hbs", "{{shout name}}/{{> part}}")
    loader = Loader(
        [tree.root],
        configure={
            HandlebarsTemplate: lambda helpers: helpers.update(
                shout=lambda this, value: _shout(value)
            )
        },
    )
    assert loader.render("page.hbs", name="web") == "WEB/WEB"


def test_a_function_runs_once_per_lookup_and_for_subclasses(tree):
    pytest.importorskip("jinja2")

    class Custom(JinjaTemplate):
        EXT = ".custom"

    tree.write("a.custom", "{{ 1 }}")
    tree.write("b.custom", "{{ 2 }}")
    calls = []
    loader = Loader(
        [tree.root],
        engines=[Custom],
        configure={JinjaTemplate: calls.append},
    )
    loader.render("a.custom")
    loader.render("b.custom")
    assert len(calls) == 1


def test_an_engine_without_an_environment_ignores_its_entry(tree):
    pytest.importorskip("chevron")
    tree.write("page.mustache", "{{name}}")
    loader = Loader([tree.root], configure={MustacheTemplate: pytest.fail})
    assert loader.render("page.mustache", name="web") == "web"


def test_configure_takes_engine_classes_and_callables():
    with pytest.raises(TypeError, match="engine class"):
        Loader([], configure={"jinja": print})
    with pytest.raises(TypeError, match="engine class"):
        Loader([], configure={JinjaTemplate: "not callable"})
