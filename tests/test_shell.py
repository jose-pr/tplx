"""The shell engine: `%{NAME}` placeholders, its configuration and defaults."""

from argparse import Namespace

import pytest

from tplx import JinjaTemplate, Loader, RenderError, ShellTemplate, UndefinedError


def render(source, mode="strict", cls=ShellTemplate, **data):
    lookup = Loader([], undefined=mode).lookup()
    return cls(source, lookup=lookup).render(data)


# -- suffix gating -----------------------------------------------------------


@pytest.mark.parametrize(
    "name, claimed",
    [
        ("boot.shtpl", True),
        ("boot.SHTPL", True),
        ("boot.cfg.shtpl", True),
        ("boot.cfg", False),
        ("boot.j2", False),
    ],
)
def test_the_shell_engine_claims_only_its_own_suffix(name, claimed):
    assert ShellTemplate.can_process(name, "") is claimed


@pytest.mark.parametrize("ext", ["tpl", ".tpl", ("tpl",), [".tpl", ".cfg"]])
def test_ext_accepts_one_value_a_dotless_one_and_a_sequence(ext):
    class Custom(ShellTemplate):
        EXT = ext

    assert Custom.can_process("boot.tpl", "") is True
    assert Custom.can_process("boot.shtpl", "") is False


@pytest.mark.parametrize("ext", [None, "*", ("*",)])
def test_ext_can_claim_every_suffix(ext):
    class CatchAll(ShellTemplate):
        EXT = ext

    assert CatchAll.can_process("boot.cfg", "") is True


def test_the_jinja_engine_claims_its_suffixes_through_ext():
    assert JinjaTemplate.EXT == (".j2", ".jinja", ".jinja2")


# -- data ----------------------------------------------------------------------


def test_nested_data_is_flattened_to_upper_snake():
    target = Namespace(hostname="web01", nic={"mac": "aa"})
    assert render("%{TARGET_HOSTNAME} %{target_nic_mac}", target=target) == "web01 aa"


def test_list_items_are_numbered():
    assert render("%{NS_0},%{NS_1}", ns=["a", "b"]) == "a,b"


def test_none_renders_empty_and_a_boolean_lowercase():
    assert render("D=%{DOMAIN} B=%{FLAG}", domain=None, flag=True) == "D= B=true"


def test_a_kickstart_keeps_its_percent_sections():
    source = "%packages\n@core\n%end\ndate +%Y%m%d %{HOST}\n"
    assert render(source, host="h1") == "%packages\n@core\n%end\ndate +%Y%m%d h1\n"


def test_a_doubled_delimiter_is_a_literal_one():
    assert render("100%% %{HOST}", host="h1") == "100% h1"


# -- delimiter and pattern ---------------------------------------------------


def test_a_subclass_can_change_the_delimiter():
    class Dollar(ShellTemplate):
        DELIMITER = "$"

    assert render("${HOST} %{HOST}", cls=Dollar, host="h1") == "h1 %{HOST}"
    assert render("$$done", cls=Dollar, host="h1") == "$done"


def test_the_unbraced_pattern_substitutes_the_bare_form_only():
    class Unbraced(ShellTemplate):
        PATTERN = "unbraced"

    assert render("%HOST %{HOST}", cls=Unbraced, host="h1") == "h1 %{HOST}"


def test_the_all_pattern_substitutes_both_forms():
    class Both(ShellTemplate):
        PATTERN = "all"

    assert render("%HOST %{HOST}", cls=Both, host="h1") == "h1 h1"


def test_an_unknown_pattern_names_the_accepted_words():
    class Broken(ShellTemplate):
        PATTERN = "curly"

    with pytest.raises(RenderError, match="braced, unbraced, all") as excinfo:
        render("x", cls=Broken)
    assert isinstance(excinfo.value.__cause__, ValueError)


def test_a_subclass_does_not_reuse_its_parents_pattern():
    assert render("%{HOST}", host="h1") == "h1"

    class Dollar(ShellTemplate):
        DELIMITER = "$"

    assert render("${HOST}", cls=Dollar, host="h1") == "h1"
    assert render("%{HOST}", host="h1") == "h1"


# -- POSIX default expressions ----------------------------------------------


def test_colon_dash_applies_to_an_unset_and_an_empty_value():
    assert render("%{MISSING:-fallback}") == "fallback"
    assert render("%{HOST:-fallback}", host="") == "fallback"
    assert render("%{HOST:-fallback}", host="h1") == "h1"


def test_bare_dash_applies_only_to_an_unset_value():
    assert render("%{MISSING-fallback}") == "fallback"
    assert render("[%{HOST-fallback}]", host="") == "[]"


def test_one_layer_of_quotes_is_stripped_from_a_default():
    assert render("%{MISSING:-'a default value'}") == "a default value"
    assert render('%{MISSING:-"a default value"}') == "a default value"
    assert render("%{MISSING:-''}") == ""
    assert render("%{MISSING:-\"it's fine}") == "\"it's fine"


def test_a_default_is_literal_text():
    assert render("%{MISSING:-%{HOST}}", host="h1") == "%{HOST}"


def test_a_default_satisfies_every_undefined_mode():
    for mode in ("strict", "lenient", "debug"):
        assert render("%{MISSING:-ok}", mode) == "ok"


def test_a_value_of_none_counts_as_no_value():
    assert render("%{HOST:-fallback}", host=None) == "fallback"


def test_an_unset_name_without_a_default_follows_the_mode():
    with pytest.raises(UndefinedError, match="MISSING"):
        render("%{MISSING}")
    assert render("%{MISSING}", "lenient") == ""
    assert render("%{MISSING}", "debug") == "%{MISSING}"
    assert render("%{MISSING:?boom}", "debug") == "%{MISSING:?boom}"


def test_two_keys_that_upper_case_alike_warn(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="tplx"):
        assert render("%{DOMAIN}", domain="a", DOMAIN="b") == "b"
    assert "two values" in caplog.text
