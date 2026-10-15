"""Registering an engine, and the priority that orders them.

`PRIORITY`, not registration order, decides: a plugin registers after the
shipped engines, and would otherwise land behind the catch-all.
"""

import pytest

from tplx import (
    DEFAULT_PRIORITY,
    FALLBACK_PRIORITY,
    CopyTemplate,
    JinjaTemplate,
    Loader,
    ShellTemplate,
    Template,
    by_priority,
    register_engine,
    registered_engines,
    unregister_engine,
)


class _Shouty(Template):
    EXT = ".shouty"

    def render_values(self, values):
        return self.source.upper()


def test_the_shipped_engines_are_registered_with_the_fallback_last():
    names = [cls.__name__ for cls in registered_engines()]
    assert names[0] == "JinjaTemplate" and names[-1] == "CopyTemplate"
    assert {
        "MakoTemplate",
        "LiquidTemplate",
        "HandlebarsTemplate",
        "MustacheTemplate",
        "ERBTemplate",
        "EPPTemplate",
        "ShellTemplate",
        "EnvsubstTemplate",
        "GoTemplate",
    } <= set(names)
    assert CopyTemplate.PRIORITY == FALLBACK_PRIORITY
    assert ShellTemplate.PRIORITY == JinjaTemplate.PRIORITY == DEFAULT_PRIORITY


def test_a_registered_engine_is_consulted_before_the_catch_all():
    register_engine(_Shouty)
    engines = Loader([]).engines
    assert engines.index(_Shouty) < engines.index(CopyTemplate)


def test_a_plugin_engine_renders_its_own_suffix(tree):
    register_engine(_Shouty)
    tree.write("boot.shouty", "quiet")
    assert Loader([tree.root]).render("boot") == "QUIET"


def test_register_returns_the_class_and_works_as_a_decorator():
    assert register_engine(_Shouty) is _Shouty

    @register_engine
    class Decorated(Template):
        EXT = ".dec"

    assert Decorated in registered_engines()


def test_register_can_set_a_priority_for_a_class_you_do_not_own():
    @register_engine(priority=50)
    class First(Template):
        EXT = ".first"

    assert First.PRIORITY == 50
    assert Loader([]).engines[0] is First


def test_registering_twice_does_not_duplicate():
    register_engine(_Shouty)
    register_engine(_Shouty)
    assert registered_engines().count(_Shouty) == 1


def test_a_second_engine_for_a_claimed_suffix_needs_another_priority():
    class OtherJinja(Template):
        EXT = ".j2"

    with pytest.raises(ValueError, match="OtherJinja and JinjaTemplate"):
        register_engine(OtherJinja)
    register_engine(OtherJinja, priority=10)
    assert Loader([]).engines[0] is OtherJinja


def test_unregister_reports_whether_it_removed_anything():
    register_engine(_Shouty)
    assert unregister_engine(_Shouty) is True
    assert unregister_engine(_Shouty) is False


def test_equal_priorities_keep_the_order_they_were_given():
    assert by_priority([ShellTemplate, JinjaTemplate]) == (ShellTemplate, JinjaTemplate)
    assert by_priority([JinjaTemplate, ShellTemplate]) == (JinjaTemplate, ShellTemplate)


def test_an_explicit_list_is_still_ordered_by_priority():
    assert Loader([], engines=[CopyTemplate, ShellTemplate]).engines == (
        ShellTemplate,
        CopyTemplate,
    )


def test_a_loader_snapshots_the_registry_at_construction():
    loader = Loader([])
    register_engine(_Shouty)
    assert _Shouty not in loader.engines
    assert _Shouty in Loader([]).engines


def test_a_lower_priority_engine_can_sit_behind_the_catch_all():
    @register_engine(priority=FALLBACK_PRIORITY - 1)
    class Lastest(Template):
        EXT = None

    assert Loader([]).engines[-1] is Lastest


def test_an_installed_entry_point_is_registered(monkeypatch):
    from tplx import _registry

    class _EntryPoint:
        name = "shouty"

        def load(self):
            return _Shouty

    class _Broken:
        name = "broken"

        def load(self):
            raise ImportError("missing dependency")

    monkeypatch.setattr(_registry, "_ENTRY_POINTS_LOADED", False)
    monkeypatch.setattr(
        "importlib.metadata.entry_points", lambda **kw: [_EntryPoint(), _Broken()]
    )
    assert _Shouty in registered_engines()


def test_a_refused_registration_changes_nothing():
    class Mine(Template):
        EXT = ".j2"
        PRIORITY = 3

    with pytest.raises(ValueError):
        register_engine(Mine, priority=DEFAULT_PRIORITY)
    assert Mine.PRIORITY == 3 and Mine not in registered_engines()


def test_re_registering_at_a_new_priority_is_checked_for_conflicts():
    class First(Template):
        EXT = ".twice"

    class Second(Template):
        EXT = ".twice"
        PRIORITY = 5

    register_engine(First)
    register_engine(Second)
    with pytest.raises(ValueError, match="First and Second"):
        register_engine(First, priority=5)
    assert First.PRIORITY == DEFAULT_PRIORITY
