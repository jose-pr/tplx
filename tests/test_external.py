"""ERB and EPP, which run `ruby` and `puppet`.

The engine-shape tests run everywhere, with Python standing in for the program;
only the rendering tests need the real programs, and skip visibly without them.
"""

import json
import shutil
import sys
import time

import pytest

from tplx import (
    DataEncoder,
    EngineUnavailableError,
    EPPTemplate,
    ERBTemplate,
    Loader,
    RenderError,
    RenderTimeoutError,
)
from tplx.engines._external import _ERB_SCRIPT

has_ruby = shutil.which("ruby") is not None
has_puppet = shutil.which("puppet") is not None


def _python(engine, script, **attrs):
    """A subclass of `engine` that runs `python -c script` instead of its program."""

    def command(self, program, template_path, values_path):
        return [program, "-c", script, template_path, values_path]

    return type(
        "Fake" + engine.__name__,
        (engine,),
        {"COMMAND": sys.executable, "command": command, **attrs},
    )


@pytest.mark.parametrize(
    "engine, env_var", [(ERBTemplate, "TPLX_RUBY"), (EPPTemplate, "TPLX_PUPPET")]
)
def test_a_missing_program_names_it_and_the_override(engine, env_var, tmp_path):
    missing = type("Missing", (engine,), {"COMMAND": str(tmp_path / "not-here")})
    with pytest.raises(EngineUnavailableError) as excinfo:
        missing("x")
    assert env_var in str(excinfo.value)


@pytest.mark.parametrize(
    "engine, env_var", [(ERBTemplate, "TPLX_RUBY"), (EPPTemplate, "TPLX_PUPPET")]
)
def test_the_env_var_wins_over_path(engine, env_var, monkeypatch, tmp_path):
    fake = tmp_path / "fake-program"
    fake.write_text("#!/bin/sh\nexit 0\n")
    monkeypatch.setenv(env_var, str(fake))
    assert engine.executable() == str(fake)


def test_the_program_reads_the_data_as_json_without_private_names():
    echo = "import sys; sys.stdout.write(open(sys.argv[2]).read())"
    engine = _python(ERBTemplate, echo)
    out = json.loads(engine("x").render(host="h1", _secret="s", _id="t1"))
    assert out == {"host": "h1"}
    lookup = Loader([], encoder=DataEncoder(expose=["_id"])).lookup()
    out = json.loads(engine("x", lookup=lookup).render(host="h1", _id="t1"))
    assert out == {"host": "h1", "_id": "t1"}


def test_a_failing_program_reports_its_stderr():
    fail = "import sys; sys.stderr.write('boom'); sys.exit(3)"
    with pytest.raises(RenderError, match="exit 3.*boom"):
        _python(ERBTemplate, fail)("x").render()


def test_a_hanging_program_times_out():
    hang = "import time; time.sleep(30)"
    engine = _python(ERBTemplate, hang, TIMEOUT=1)
    with pytest.raises(RenderTimeoutError, match="within 1s") as excinfo:
        engine("x").render()
    assert isinstance(excinfo.value, TimeoutError)


def test_crlf_is_normalised_only_when_the_engine_asks():
    emit = "import sys; sys.stdout.buffer.write(b'a\\r\\nb\\r\\n')"
    assert _python(EPPTemplate, emit)("x").render() == "a\nb\n"
    assert _python(EPPTemplate, emit, NEWLINES=None)("x").render() == "a\r\nb\r\n"


def test_a_sentinel_is_written_after_the_template_and_removed_from_the_output():
    echo = "import sys; sys.stdout.write(open(sys.argv[1]).read() + chr(10))"
    engine = _python(EPPTemplate, echo)
    assert engine("body").render() == "body"
    assert engine("body\n").render() == "body\n"


def test_the_erb_script_stops_ruby_translating_stdout():
    assert "$stdout.binmode" in _ERB_SCRIPT
    assert ERBTemplate.NEWLINES is None


# -- the real programs -------------------------------------------------------

DATA = {
    "target": {"hostname": "host1"},
    "image": {"_id": "debian"},
    "nameservers": ["10.0.0.53", "10.0.0.54"],
}
EXPECTED = "host host1 image debian\nnameserver 10.0.0.53\nnameserver 10.0.0.54\n"


@pytest.mark.skipif(not has_ruby, reason="needs ruby installed")
def test_erb_renders_through_ruby(tree):
    tree.write(
        "boot.erb",
        "host <%= @target['hostname'] %> image <%= @image['_id'] %>\n"
        "<% @nameservers.each do |ns| -%>\nnameserver <%= ns %>\n<% end -%>\n",
    )
    assert (
        Loader([tree.root], encoder=DataEncoder(expose=["_id"])).render(
            "boot.erb", DATA
        )
        == EXPECTED
    )


@pytest.mark.skipif(not has_ruby, reason="needs ruby installed")
def test_erb_reports_a_template_error_from_ruby(tree):
    tree.write("bad.erb", "<%= @target[ %>")
    with pytest.raises(RenderError, match="ruby failed to render"):
        Loader([tree.root]).render("bad.erb", DATA)


@pytest.mark.skipif(not has_ruby, reason="needs ruby installed")
def test_erb_keeps_the_templates_own_bytes(tree):
    tree.write("nonl.erb", "label <%= @target['hostname'] %>")
    assert Loader([tree.root]).render("nonl.erb", DATA) == "label host1"


@pytest.mark.skipif(not has_puppet, reason="needs puppet installed")
def test_epp_renders_through_puppet(tree):
    tree.write(
        "boot.epp",
        "host <%= $target['hostname'] %> image <%= $image['_id'] %>\n"
        "<% $nameservers.each |$ns| { -%>\nnameserver <%= $ns %>\n<% } -%>\n",
    )
    assert (
        Loader([tree.root], encoder=DataEncoder(expose=["_id"])).render(
            "boot.epp", DATA
        )
        == EXPECTED
    )


@pytest.mark.skipif(not has_puppet, reason="needs puppet installed")
def test_epp_keeps_the_templates_own_bytes(tree):
    tree.write("nonl.epp", "label <%= $target['hostname'] %>")
    assert Loader([tree.root]).render("nonl.epp", DATA) == "label host1"
    tree.write("nl.epp", "label\n")
    assert Loader([tree.root]).render("nl.epp", DATA) == "label\n"


@pytest.mark.skipif(not has_puppet, reason="needs puppet installed")
def test_epp_reports_a_template_error_from_puppet(tree):
    tree.write("bad.epp", "<%= $target[ %>")
    with pytest.raises(RenderError, match="puppet failed to render"):
        Loader([tree.root]).render("bad.epp", DATA)


@pytest.mark.skipif(not has_ruby, reason="needs ruby installed")
def test_erb_keeps_the_whole_hash_in_context_whatever_the_data_names(tree):
    tree.write("c.erb", "<%= @context['context'] %>|<%= @context.class %>|<%= @n %>")
    rendered = Loader([tree.root]).render("c.erb", context="mine", n=float("nan"))
    assert rendered == "mine|Hash|nan"


def test_a_timeout_kills_the_programs_children_too():
    spawn = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "time.sleep(30)"
    )
    engine = _python(ERBTemplate, spawn, TIMEOUT=1)
    start = time.monotonic()
    with pytest.raises(RenderTimeoutError):
        engine("x").render()
    assert time.monotonic() - start < 10


def test_output_that_is_not_utf8_is_decoded_with_replacement_characters():
    emit = "import sys; sys.stdout.buffer.write(b'a\\xffb')"
    assert _python(ERBTemplate, emit)("x").render() == "a\ufffdb"
