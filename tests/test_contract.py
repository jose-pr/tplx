"""Every shipped engine passes the contract suite a third-party engine runs."""

import importlib.util
import shutil
import sys

import pytest

import tplx
from tplx.testing import EngineContract


def _needs(module):
    return pytest.mark.skipif(
        importlib.util.find_spec(module) is None,
        reason=f"needs {module}",
    )


@_needs("jinja2")
class TestJinja(EngineContract):
    engine = tplx.JinjaTemplate
    source = "{{ name }}"
    expected = "tplx"


@_needs("mako")
class TestMako(EngineContract):
    engine = tplx.MakoTemplate
    source = "${name}"
    expected = "tplx"


@_needs("liquid")
class TestLiquid(EngineContract):
    engine = tplx.LiquidTemplate
    source = "{{ name }}"
    expected = "tplx"


@_needs("pybars")
class TestHandlebars(EngineContract):
    engine = tplx.HandlebarsTemplate
    source = "{{name}}"
    expected = "tplx"


@_needs("chevron")
class TestMustache(EngineContract):
    engine = tplx.MustacheTemplate
    source = "{{name}}"
    expected = "tplx"


class TestShell(EngineContract):
    engine = tplx.ShellTemplate
    source = "%{NAME}"
    expected = "tplx"


class TestCopy(EngineContract):
    engine = tplx.CopyTemplate
    source = b"as is"
    expected = b"as is"
    filename = "contract.bin"


class _PythonEcho(tplx.ERBTemplate):
    """ERB's machinery with Python in place of ruby: prints the `name` value."""

    COMMAND = sys.executable

    def command(self, program, template_path, values_path):
        script = (
            "import json,sys; sys.stdout.write(json.load(open(sys.argv[1]))['name'])"
        )
        return [program, "-c", script, values_path]


class TestSubprocess(EngineContract):
    engine = _PythonEcho
    source = "ignored"
    expected = "tplx"


@pytest.mark.skipif(shutil.which("ruby") is None, reason="needs ruby installed")
class TestERB(EngineContract):
    engine = tplx.ERBTemplate
    source = "<%= @name %>"
    expected = "tplx"


@pytest.mark.skipif(shutil.which("puppet") is None, reason="needs puppet installed")
class TestEpp(EngineContract):
    engine = tplx.EppTemplate
    source = "<%= $name %>"
    expected = "tplx"
