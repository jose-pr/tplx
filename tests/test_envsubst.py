"""`EnvsubstTemplate` and the shell engine's features, against the real tools.

Expectations are what GNU envsubst 0.26, github.com/a8m/envsubst 1.4.3 and
github.com/drone/envsubst 1.0.3 printed for the same input with A=hello, E
empty, B=world, P=/usr/local/bin, lower=x and U unset. Where tplx departs from
a tool on purpose, the case says so.
"""

import pytest

from tplx import EnvsubstTemplate, Loader, ShellTemplate, UndefinedError

DATA = {"A": "hello", "E": "", "B": "world", "P": "/usr/local/bin", "lower": "x"}


class A8m(EnvsubstTemplate):
    DIALECT = "a8m"


class Drone(EnvsubstTemplate):
    DIALECT = "drone"


def render(cls, source, mode="lenient", **data):
    lookup = Loader([], undefined=mode).lookup()
    return cls(source, lookup=lookup).render({**DATA, **data})


GNU = [
    ("plain $A ${A}", "plain hello hello"),
    ("escape $$ $$A $${A}", "escape $$ $hello $hello"),
    ("backslash \\$A", "backslash \\hello"),
    ("greedy $Ax ${A}x", "greedy  hellox"),
    ("unset [$U] [${U}]", "unset [] []"),
    ("dash ${U-d} ${U:-d} ${U=d} ${U:+d}", "dash ${U-d} ${U:-d} ${U=d} ${U:+d}"),
    ("nested ${U:-$B} ${U:-${B}}", "nested ${U:-world} ${U:-world}"),
    ("slice ${A:1:3} ${A//l/L} ${#A} ${A^^}", "slice ${A:1:3} ${A//l/L} ${#A} ${A^^}"),
    ("nonident ${1} $1 ${A.b}", "nonident ${1} $1 ${A.b}"),
    ("unclosed ${A", "unclosed ${A"),
]

A8M = [
    ("plain $A ${A}", "plain hello hello"),
    ("escape $$ $$A $${A}", "escape $ $A ${A}"),
    ("dash ${U-d} ${E-d} ${A-d}", "dash d  hello"),
    ("colondash ${U:-d} ${E:-d} ${A:-d}", "colondash d d hello"),
    ("eq ${U=d} ${E=d} ${A=d}", "eq d  hello"),
    ("coloneq ${U:=d} ${E:=d} ${A:=d}", "coloneq d d hello"),
    ("plus ${U+d} ${E+d} ${A+d}", "plus  d d"),
    ("colonplus ${U:+d} ${E:+d} ${A:+d}", "colonplus   d"),
    ("nested ${U:-$B}", "nested world"),
    ('quoted ${U:-"q d"}', 'quoted "q d"'),
    ("brace ${U:-a}b}", "brace ab}"),
    # a8m prints "}" and "pre${Bpost}" here; tplx substitutes nested braces.
    ("nested-brace ${U:-${B}} ${U:-pre${B}post}", "nested-brace world preworldpost"),
]

DRONE = [
    ("plain $A ${A}", "plain $A hello"),
    ("escape $$ $${A}", "escape $ ${A}"),
    ("colondash ${U:-d} ${E:-d} ${A:-d}", "colondash d d hello"),
    ("nested ${U:-$B} ${U:-${B}} ${U:-pre${B}post}", "nested $B world preworldpost"),
    ("slice ${A:1} ${A:1:3} ${A:9} ${A:0:0} ${A:2:9}", "slice ello ell   llo"),
    ("replace ${P/\\//:} ${P//\\//:}", "replace :usr/local/bin :usr:local:bin"),
    (
        "replace ${A/l/L} ${A//l/L} ${A/#h/H} ${A/%o/O}",
        "replace heLlo heLLo Hello hellO",
    ),
    ("replace-empty ${A/l/} ${A//l/} ${A/x/y}", "replace-empty helo heo hello"),
    ("trim ${P#*/} ${P##*/} ${P%/*} ${P%%/*}", "trim usr/local/bin bin /usr/local "),
    ("trim ${A#h*} ${A##*l} ${A%l*} ${A%%l*}", "trim ello o hel he"),
    ("case ${A^} ${A^^} ${B,} ${B,,}", "case Hello HELLO world world"),
    ("length ${#A} ${#U}", "length 5 0"),
    # drone returns the whole value for a negative offset and panics on a
    # negative length; tplx slices as bash does.
    ("negative ${A: -2} ${A:(-2)} ${A:1:-1}", "negative lo lo ell"),
    # drone matches a replacement pattern literally; tplx, as bash, as a glob.
    ("glob ${A/l*/X} ${A//?/.}", "glob heX ....."),
]


@pytest.mark.parametrize("source, expected", GNU)
def test_gnu_is_the_default_dialect(source, expected):
    assert render(EnvsubstTemplate, source) == expected


@pytest.mark.parametrize("source, expected", A8M)
def test_the_a8m_dialect(source, expected):
    assert render(A8m, source) == expected


@pytest.mark.parametrize("source, expected", DRONE)
def test_the_drone_dialect(source, expected):
    assert render(Drone, source) == expected


def test_names_match_whatever_their_case():
    # GNU and a8m print " x" here: their names are case-sensitive.
    assert render(EnvsubstTemplate, "$LOWER $lower") == "x x"


def test_an_undefined_name_follows_the_mode():
    with pytest.raises(UndefinedError, match=r"\$U"):
        render(EnvsubstTemplate, "a $U", "strict")
    nginx = "proxy_pass http://$BACKEND$request_uri;"
    assert (
        render(EnvsubstTemplate, nginx, "debug", BACKEND="b:80")
        == "proxy_pass http://b:80$request_uri;"
    )
    assert render(Drone, "${U:1:2}|${U//a/b}", "debug") == "${U:1:2}|${U//a/b}"


def test_a_subclass_can_add_features_to_a_dialect():
    class GnuWithDefaults(EnvsubstTemplate):
        FEATURES = frozenset({"default"})

    assert render(GnuWithDefaults, "${U:-d} $$") == "d $$"


def test_an_unknown_dialect_or_feature_is_refused():
    class Bad(EnvsubstTemplate):
        DIALECT = "busybox"

    class Typo(ShellTemplate):
        FEATURES = frozenset({"slices"})

    for cls, words in ((Bad, "gnu, a8m, drone"), (Typo, "slices")):
        with pytest.raises(ValueError, match=words):
            cls.syntax()


def test_envsubst_claims_its_suffixes_and_renders_through_a_loader(tree):
    tree.write("nginx.conf.template", "listen ${PORT};\n")
    tree.write("app.env.envsubst", "PORT=$PORT\n")
    loader = Loader([tree.root])
    assert loader.render("nginx.conf", PORT=8080) == "listen 8080;\n"
    assert loader.render("app.env", PORT=8080) == "PORT=8080\n"


# -- the shell engine gains slices and replacements -------------------------


def shell(source, **data):
    return render(ShellTemplate, source, "strict", **data)


def test_the_shell_engine_slices_and_replaces():
    assert shell("%{HOST:0:5} %{HOST: -3}", host="web01.lan") == "web01 lan"
    assert shell("%{PATH//:/ } %{PATH/#\\/usr/~}", path="/usr/bin:/bin") == (
        "/usr/bin /bin ~/bin:/bin"
    )


def test_the_shell_engine_keeps_what_it_does_not_know_as_text():
    assert shell("%{HOST^^} %{#HOST} %{HOST##*.}", host="web01.lan") == (
        "%{HOST^^} %{#HOST} %{HOST##*.}"
    )
