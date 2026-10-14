"""The README's and the docs' examples run as written."""

import json
import pathlib
import re
import shlex

import pytest

pytest.importorskip("jinja2", reason="needs the 'jinja' extra")

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES = [ROOT / "README.md", ROOT / "docs" / "index.md", ROOT / "docs" / "cli.md"]
FENCE = re.compile(r"^```(\w+)\n(.*?)^```", re.MULTILINE | re.DOTALL)


def _blocks(language):
    for page in PAGES:
        for found in FENCE.finditer(page.read_text(encoding="utf-8")):
            if found.group(1) == language:
                yield page.name, found.group(2)


def _commands():
    for page, block in _blocks("bash"):
        for line in block.splitlines():
            line = line.split("  #", 1)[0].strip()
            if line.startswith("tplx "):
                yield page, shlex.split(line)[1:]


@pytest.fixture
def project(tmp_path, monkeypatch):
    templates = tmp_path / "templates"
    (templates / "debian").mkdir(parents=True)
    (templates / "boot.cfg.j2").write_text(
        "host {{ hostname | default('any') }} {{ release | default('') }}\n"
    )
    (tmp_path / "host.json").write_text(json.dumps({"hostname": "web01"}))
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize("page", [page.name for page in PAGES])
def test_a_pages_python_examples_run_in_order(project, page):
    namespace = {}  # a later block builds on an earlier one, as a reader would
    for name, source in _blocks("python"):
        if name == page:
            exec(compile(source, page, "exec"), namespace)


@pytest.mark.parametrize("page, argv", list(_commands()))
def test_a_command_example_runs(project, page, argv, capsys):
    pytest.importorskip("duho", reason="needs the 'cli' extra")
    from tplx.cli import main

    assert main(argv) == 0
