"""The Go `text/template` engine, against what Go itself renders.

`go_reference.json` holds cases rendered by Go 1.26's `text/template`, with
the same data; a case Go refused to execute expects an error here too.
"""

import json
import pathlib

import pytest

gotpl = pytest.importorskip("gotpl", reason="needs the 'go' extra (Python 3.11+)")

from tplx import (  # noqa: E402
    GoTemplate,
    Loader,
    RenderError,
    TemplateNotFound,
    UndefinedError,
)

REFERENCE = json.loads(
    (pathlib.Path(__file__).parent / "go_reference.json").read_text(encoding="utf-8")
)
MODES = {"": "debug", "zero": "lenient", "error": "strict"}


@pytest.mark.parametrize(
    "case", REFERENCE["cases"], ids=[case["name"] for case in REFERENCE["cases"]]
)
def test_it_renders_what_go_renders(tree, case):
    tree.write("t.tmpl", case["source"])
    loader = Loader([tree.root], undefined=MODES[case["missingkey"]])
    if case["expected"] is None:
        with pytest.raises(RenderError):
            loader.render("t", REFERENCE["data"])
    else:
        assert loader.render("t", REFERENCE["data"]) == case["expected"]


def test_objects_are_read_by_attribute(tree):
    from types import SimpleNamespace

    tree.write("t.tmpl", "{{.target.hostname}} {{range .ns}}{{.}};{{end}}")
    data = {"target": SimpleNamespace(hostname="web01"), "ns": ["a", "b"]}
    assert Loader([tree.root]).render("t", data) == "web01 a;b;"


def test_a_missing_key_follows_the_mode(tree):
    tree.write("t.tmpl", "[{{.nope}}]")
    with pytest.raises(UndefinedError, match="nope"):
        Loader([tree.root]).render("t")
    for mode in ("lenient", "debug"):
        assert Loader([tree.root], undefined=mode).render("t") == "[<no value>]"


def test_a_template_name_resolves_through_the_lookup(tree):
    tree.write("part.tmpl", '{{define "inner"}}({{.}}){{end}}<{{.x}}>')
    tree.write("page.tmpl", '{{template "part" .}}{{template "inner" .x}}')
    assert Loader([tree.root]).render("page", x=1) == "<1>(1)"


def test_another_engines_file_renders_with_the_pipelines_data(tree):
    tree.write("net.shtpl", "IP=%{IP}")
    tree.write("page.tmpl", '[{{template "net" .}}][{{template "net" .sub}}]')
    rendered = Loader([tree.root], undefined="lenient").render(
        "page", ip="1.2.3.4", sub={"ip": "5.6.7.8"}
    )
    assert rendered == "[IP=1.2.3.4][IP=5.6.7.8]"


def test_a_name_found_nowhere_raises_only_when_it_runs_under_strict(tree):
    tree.write("page.tmpl", '{{if .go}}{{template "nope" .}}{{end}}ok')
    loader = Loader([tree.root])
    assert loader.render("page", go=False) == "ok"
    with pytest.raises(TemplateNotFound):
        loader.render("page", go=True)
    assert Loader([tree.root], undefined="lenient").render("page", go=True) == "ok"


def test_a_changed_include_recompiles_the_template(tree):
    import os
    import time

    part = tree.write("part.tmpl", "v1")
    tree.write("page.tmpl", '{{template "part"}}')
    lookup = Loader([tree.root]).lookup()
    assert lookup.render("page") == "v1"
    part.write_bytes(b"v2")
    later = time.time() + 5
    os.utime(part, (later, later))
    assert lookup.render("page") == "v2"


def test_sprig_is_one_configure_away(tree):
    from gotpl.funcs.sprig import text_func_map

    tree.write("t.tmpl", '{{ .name | upper | quote }} {{ default "d" .none }}')
    loader = Loader(
        [tree.root],
        undefined="lenient",
        configure={GoTemplate: lambda functions: functions.update(text_func_map())},
    )
    assert loader.render("t", name="web") == '"WEB" d'


def test_gotmpl_is_claimed_too(tree):
    tree.write("values.yaml.gotmpl", "port: {{.port}}\n")
    assert Loader([tree.root]).render("values.yaml", port=80) == "port: 80\n"
