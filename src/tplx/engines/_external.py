"""Engines that render through another language's own program: ERB and EPP.

The template and the data go to the real renderer: the data is written as
JSON, the program runs as a subprocess, and its standard output is the result.
A render therefore needs the program installed and spawns a process.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import tempfile
from typing import Any, ClassVar, Dict, List, Mapping, Optional

from .._loader import Lookup
from .._template import Template
from ..exceptions import EngineUnavailableError, RenderError, RenderTimeoutError

#: How much of a failing program's standard error an exception message keeps.
_STDERR_LIMIT = 2000


#: Seconds to wait for the pipes to close once a timed-out program is killed.
_DRAIN_SECONDS = 5


def _kill_tree(process: "subprocess.Popen[bytes]") -> None:
    """Kill `process` and everything it started.

    A program that is a shim (`puppet.bat`, a shell wrapper) runs the real
    renderer as its child, which would otherwise keep running and hold the
    output pipes open.
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    process.kill()


def _run(argv: List[str], timeout: float, program: str) -> bytes:
    """Run `argv` with no input and return its standard output.

    The program runs in its own process group, so a timeout kills it and its
    children.

    :raises RenderTimeoutError: it ran longer than `timeout` seconds.
    :raises RenderError: it exited non-zero; the message holds the end of its
        standard error.
    """
    group: Dict[str, Any] = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    with subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        **group,
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _kill_tree(process)
            try:
                process.communicate(timeout=_DRAIN_SECONDS)
            except subprocess.TimeoutExpired:
                pass
            raise RenderTimeoutError(
                f"{program} did not finish rendering within {timeout}s"
            ) from exc
    if process.returncode != 0:
        text = stderr.decode("utf-8", errors="replace").strip()
        raise RenderError(
            f"{program} failed to render the template (exit {process.returncode}): "
            f"{text[-_STDERR_LIMIT:]}"
        )
    return stdout


class SubprocessTemplate(Template):
    """Base for an engine that runs another language's renderer.

    A subclass sets `COMMAND`, `ENV_VAR`, `EXT` and implements `command()`.
    The data reaches the program as JSON, made by the loader's
    `DataEncoder.json`: structures become objects, anything else its text, and
    `_`-prefixed names are dropped unless the encoder's `expose` lists them. Undefined modes do not apply;
    missing data is the other language's own null.
    """

    #: The program, looked up on `PATH` unless it is a path.
    COMMAND: ClassVar[str] = ""
    #: Environment variable naming the program's path instead.
    ENV_VAR: ClassVar[str] = ""
    #: Seconds before a render is abandoned with `RenderTimeoutError`.
    TIMEOUT: ClassVar[float] = 60
    #: Base name the template is written under, so the program's messages name
    #: something recognisable.
    BASENAME: ClassVar[str] = "template"
    #: `"lf"` to turn CRLF in the output into LF; `None` keeps what the program
    #: wrote.
    NEWLINES: ClassVar[Optional[str]] = None
    #: File name for the JSON data; some programs insist on an extension.
    VALUES_NAME: ClassVar[str] = "values.json"
    #: Text appended to the template and removed from the output, with the
    #: newline a program adds after it, for a program that ends its output with
    #: a newline the template did not write.
    SENTINEL: ClassVar[Optional[str]] = None

    def __init__(
        self,
        source: str,
        *,
        lookup: "Optional[Lookup]" = None,
        origin: str = "<string>",
    ) -> None:
        super().__init__(source, lookup=lookup, origin=origin)
        # Fail while loading, where the file that needs the program is named.
        self.executable()

    @classmethod
    def executable(cls) -> str:
        """The program's full path.

        :raises EngineUnavailableError: it is not installed.
        """
        name = (os.environ.get(cls.ENV_VAR) if cls.ENV_VAR else None) or cls.COMMAND
        found = name if os.path.isabs(name) else shutil.which(name)
        if not found or not os.path.exists(found):
            raise EngineUnavailableError(
                f"the {cls.__name__.replace('Template', '').lower()} engine needs "
                f"{cls.COMMAND!r} installed and on PATH"
                + (f"; or set {cls.ENV_VAR} to its path" if cls.ENV_VAR else "")
            )
        return found

    def command(self, program: str, template_path: str, values_path: str) -> List[str]:
        """The argument list to run."""
        raise NotImplementedError

    def render_values(self, values: "Mapping[str, Any]") -> str:
        program = self.executable()
        document = self.encoder.json(values)
        ext = self.EXT if isinstance(self.EXT, str) else (self.EXT or ("",))[0]
        with tempfile.TemporaryDirectory(prefix="tplx-") as workdir:
            template_path = os.path.join(workdir, self.BASENAME + ext)
            values_path = os.path.join(workdir, self.VALUES_NAME)
            with open(template_path, "w", encoding="utf-8", newline="") as handle:
                handle.write(self.source + (self.SENTINEL or ""))
            with open(values_path, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(document, handle, allow_nan=False)
            output = _run(
                self.command(program, template_path, values_path),
                self.TIMEOUT,
                self.COMMAND,
            )
        rendered = output.decode("utf-8", errors="replace")
        if self.NEWLINES == "lf":
            rendered = rendered.replace("\r\n", "\n")
        if self.SENTINEL:
            for tail in (self.SENTINEL + "\n", self.SENTINEL):
                if rendered.endswith(tail):
                    rendered = rendered[: -len(tail)]
                    break
        return rendered


#: Reads the JSON into `@context` and each other top-level name that is a legal
#: Ruby instance variable into `@name`; a name `context` stays in `@context`.
#: `print`, not `puts`, so the trailing newline is the template's;
#: `$stdout.binmode` so Windows ruby writes "\n" unchanged.
_ERB_SCRIPT = """
require 'erb'
require 'json'
$stdout.binmode
@context = JSON.parse(File.read(ARGV[0]))
@context.each do |key, value|
  next if key == 'context'
  instance_variable_set("@#{key}", value) if key =~ /\\A[a-z_][A-Za-z0-9_]*\\z/
end
print ERB.new(File.read(ARGV[1]), trim_mode: '-').result(binding)
"""


class ERBTemplate(SubprocessTemplate):
    """An ERB template, rendered by the system `ruby` (`TPLX_RUBY` names another).

    `@context` is the whole data hash and each other top-level name is also an
    instance variable: `<%= @target['hostname'] %>`; a name `context` is
    `@context['context']`. `<%- -%>` trims.
    """

    EXT = (".erb",)
    COMMAND = "ruby"
    ENV_VAR = "TPLX_RUBY"

    def command(self, program: str, template_path: str, values_path: str) -> List[str]:
        return [program, "-e", _ERB_SCRIPT, values_path, template_path]


class EPPTemplate(SubprocessTemplate):
    """A Puppet EPP template, rendered by `puppet epp render` (`TPLX_PUPPET` names another).

    Every top-level name is an EPP parameter: `<%= $target['hostname'] %>`.
    The output is the template's own bytes: no newline is added at the end.
    CRLF in puppet's output is turned into LF, so the result does not depend on
    the platform; a `.epp` template cannot emit CRLF on purpose.
    """

    EXT = (".epp",)
    COMMAND = "puppet"
    ENV_VAR = "TPLX_PUPPET"
    NEWLINES = "lf"
    # `puppet epp render` ends its output with a newline when the template does
    # not; the sentinel makes that newline removable.
    SENTINEL = "\x1e"
    # `puppet epp render` refuses a values file that is not .yaml or .pp; JSON
    # is valid YAML, so only the name changes.
    VALUES_NAME = "values.yaml"

    def command(self, program: str, template_path: str, values_path: str) -> List[str]:
        return [program, "epp", "render", "--values_file", values_path, template_path]
