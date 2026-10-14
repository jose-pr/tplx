"""Finding a file by name, choosing its engine, and what a render sees."""

import logging
import os
import time
from types import SimpleNamespace

import pytest

import tplx
from tplx import (
    CopyTemplate,
    JinjaTemplate,
    Loader,
    NoEngineError,
    ShellTemplate,
    TemplateNotFound,
)

pytest.importorskip("jinja2", reason="needs the 'jinja' extra")


# -- resolution --------------------------------------------------------------


def test_a_stem_names_the_file_and_the_suffix_picks_the_engine(tree):
    tree.write("boot.cfg.j2", "j={{ x }}")
    tree.write("motd.shtpl", "s=%{X}")
    loader = Loader([tree.root])
    assert loader.render("boot.cfg", {"x": 1}) == "j=1"
    assert loader.render("motd", {"x": 2}) == "s=2"


def test_an_exact_file_name_beats_a_stem_match(tree):
    tree.write("boot.j2", "real")
    tree.write("boot.j2.bak", "STALE")
    assert Loader([tree.root]).render("boot.j2") == "real"


def test_stem_matches_resolve_to_the_lowest_name(tree):
    tree.write("boot.shtpl", "shell")
    tree.write("boot.j2", "jinja")
    assert Loader([tree.root]).render("boot") == "jinja"


def test_roots_are_searched_in_order(tree, tmp_path):
    second = tmp_path / "second"
    second.mkdir()
    tree.write("a.j2", "second", root=second)
    tree.write("b.j2", "first")
    tree.write("b.j2", "second", root=second)
    loader = Loader([tree.root, second])
    assert loader.render("a.j2") == "second"
    assert loader.render("b.j2") == "first"


def test_a_name_with_a_directory_keeps_it(tree):
    tree.write("debian/boot.j2", "nested")
    assert Loader([tree.root]).render("debian/boot") == "nested"


def test_templates_are_read_as_utf8(tree):
    tree.write("u.j2", "café-日本")
    assert Loader([tree.root]).render("u.j2") == "café-日本"


def test_a_name_cannot_escape_the_roots(tree):
    with pytest.raises(TemplateNotFound, match="escapes"):
        Loader([tree.root]).render("../../etc/passwd")


def test_a_missing_name_is_template_not_found(tree):
    with pytest.raises(TemplateNotFound) as excinfo:
        Loader([tree.root]).render("nothing")
    assert isinstance(excinfo.value, LookupError)
    assert excinfo.value.name == "nothing"


def test_the_default_root_is_templates_in_the_working_directory(tree, monkeypatch):
    monkeypatch.chdir(tree.root.parent)
    tree.write("d.j2", "default")
    assert Loader().render("d.j2") == "default"


# -- candidates and paths ----------------------------------------------------


def test_candidates_are_tried_most_specific_first(tree):
    tree.write("web01.boot.j2", "host-specific")
    tree.write("boot.j2", "generic")
    loader = Loader([tree.root])

    def candidates(name):
        return [f"web01.{name}", name]

    assert loader.render("boot", candidates=candidates) == "host-specific"
    assert loader.render("boot") == "generic"


def test_a_relative_path_is_searched_inside_each_root_before_the_roots(tree):
    tree.write("debian/boot.j2", "debian")
    tree.write("boot.j2", "generic")
    assert Loader([tree.root]).render("boot", paths=["debian"]) == "debian"


def test_an_absolute_path_is_used_as_given(tree, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    tree.write("boot.j2", "outside", root=outside)
    assert Loader([tree.root]).render("boot", paths=[outside.resolve()]) == "outside"


def test_a_uri_path_is_not_joined_to_a_root():
    class Remote:
        """Stands in for a remote path object: only its text matters here."""

        def __str__(self):
            return "http://boot.example/t"

    remote = Remote()
    lookup = Loader(["templates"]).lookup(paths=[remote])
    assert lookup.search_paths()[0] is remote


def test_the_same_arguments_give_the_same_lookup():
    loader = Loader([])

    def candidates(name):
        return [name]

    assert loader.lookup(candidates=candidates) is loader.lookup(candidates=candidates)
    assert loader.lookup(paths=["a"]) is not loader.lookup(paths=["b"])


# -- engines and bytes -------------------------------------------------------


def test_an_unclaimed_file_is_copied_byte_for_byte(tree):
    tree.write("grub.cfg", b"linux /vmlinuz 100%\r\n\xff")
    assert Loader([tree.root]).render("grub.cfg") == b"linux /vmlinuz 100%\r\n\xff"


def test_a_text_engine_refuses_a_file_that_is_not_utf8(tree):
    tree.write("boot.j2", b"host=\xff\xfe")
    with pytest.raises(NoEngineError, match="not valid UTF-8"):
        Loader([tree.root]).render("boot.j2")


def test_without_a_catch_all_the_error_names_what_each_engine_claims(tree):
    tree.write("boot.cfg", "x")
    loader = Loader([tree.root], engines=[JinjaTemplate, ShellTemplate])
    with pytest.raises(NoEngineError) as excinfo:
        loader.render("boot.cfg")
    message = str(excinfo.value)
    assert "boot.cfg" in message and ".shtpl" in message and ".j2" in message


def test_a_copy_that_still_holds_placeholders_warns(tree, caplog):
    tree.write("boot.cfg", "kernel %{KERNEL}")
    with caplog.at_level(logging.WARNING, logger="tplx"):
        assert Loader([tree.root]).render("boot.cfg") == b"kernel %{KERNEL}"
    assert ".shtpl" in caplog.text


def test_an_escaped_delimiter_alone_does_not_warn(tree, caplog):
    tree.write("notes.txt", "disk 100%% full")
    with caplog.at_level(logging.WARNING, logger="tplx"):
        Loader([tree.root]).render("notes.txt")
    assert caplog.text == ""


def test_a_compile_error_is_a_render_error_naming_the_file(tree):
    tree.write("bad.j2", "{% if %}")
    with pytest.raises(tplx.RenderError, match="bad.j2") as excinfo:
        Loader([tree.root]).render("bad.j2")
    assert excinfo.value.__cause__ is not None


def test_an_engine_failure_is_a_render_error(tree):
    tree.write("div.j2", "{{ 1 // 0 }}")
    with pytest.raises(tplx.RenderError, match="JinjaTemplate failed") as excinfo:
        Loader([tree.root]).render("div.j2")
    assert isinstance(excinfo.value.__cause__, ZeroDivisionError)


# -- caching -----------------------------------------------------------------


def test_a_compiled_template_is_reused_until_its_file_changes(tree):
    path = tree.write("cached.shtpl", "v1")
    lookup = Loader([tree.root]).lookup()
    first = lookup.get("cached")
    assert lookup.get("cached") is first and first.is_up_to_date
    path.write_bytes(b"v2")
    later = time.time() + 5
    os.utime(path, (later, later))
    assert first.is_up_to_date is False
    assert lookup.render("cached") == "v2"


# -- what a render sees ------------------------------------------------------


def test_globals_then_data_then_keywords(tree):
    tree.write("n.j2", "{{ a }} {{ b }} {{ c }}")
    loader = Loader([tree.root], globals={"a": "g", "b": "g", "c": "g"})
    assert loader.render("n.j2", {"b": "d", "c": "d"}, c="k") == "g d k"


def test_keywords_alone_are_the_data(tree):
    # `name` and `data` are positional-only, so they are free as template names.
    tree.write("k.j2", "{{ name }} {{ data }} {{ x }}")
    loader = Loader([tree.root])
    assert loader.render("k.j2", name="n", data="d", x=1) == "n d 1"
    assert loader.lookup().render("k.j2", name="n", data="d", x=2) == "n d 2"
    assert loader.get("k.j2").render(name="n", data="d", x=3) == "n d 3"


def test_a_data_name_that_is_a_lookup_option_goes_in_data(tree):
    tree.write("p.j2", "{{ paths }}")
    assert Loader([tree.root]).render("p.j2", {"paths": "data"}) == "data"


def test_objects_are_read_by_attribute(tree):
    tree.write("o.j2", "{{ target.hostname }}")
    target = SimpleNamespace(hostname="web01")
    assert Loader([tree.root]).render("o.j2", target=target) == "web01"


def test_an_unknown_undefined_mode_is_refused():
    with pytest.raises(ValueError, match="strict, lenient, debug"):
        Loader([], undefined="sloppy")


def test_a_template_renders_without_a_loader():
    assert JinjaTemplate("{{ x }}-{{ y }}").render({"x": 1}, y=2) == "1-2"
    assert CopyTemplate("as is").render() == b"as is"


# -- several names -----------------------------------------------------------


def test_a_list_of_names_takes_the_first_that_exists(tree):
    tree.write("boot.cfg.j2", "generic")
    loader = Loader([tree.root])
    assert loader.render(["web01.boot.cfg", "boot.cfg"]) == "generic"
    tree.write("web01.boot.cfg.j2", "web01")
    assert Loader([tree.root]).render(["web01.boot.cfg", "boot.cfg"]) == "web01"


def test_each_name_is_expanded_by_the_candidates_before_the_next(tree):
    tree.write("host.b.j2", "host b")
    tree.write("a.j2", "plain a")

    def host(name):
        return [f"host.{name}", name]

    # `a` (as `host.a`, then `a`) is tried in full before `b`.
    assert Loader([tree.root]).render(["a", "b"], candidates=host) == "plain a"


def test_when_none_is_found_the_error_names_them_all(tree):
    with pytest.raises(TemplateNotFound, match="'x', 'y'") as excinfo:
        Loader([tree.root]).render(["x", "y"])
    assert excinfo.value.names == ("x", "y") and excinfo.value.name == "x"


def test_every_name_in_a_list_is_checked_for_escapes(tree):
    tree.write("ok.j2", "ok")
    with pytest.raises(TemplateNotFound, match="escapes"):
        Loader([tree.root]).render(["ok", "../secret"])


def test_a_list_and_a_name_are_cached_apart(tree):
    tree.write("a.j2", "a")
    tree.write("b.j2", "b")
    lookup = Loader([tree.root]).lookup()
    assert lookup.render("b") == "b"
    assert lookup.render(["a", "b"]) == "a"


def test_an_empty_list_is_refused():
    with pytest.raises(ValueError, match="no template name"):
        Loader([]).render([])
