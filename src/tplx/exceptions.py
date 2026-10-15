"""The errors tplx raises. Every one derives from `TplxError`."""

from __future__ import annotations

from typing import Optional, Sequence, Union

__all__ = [
    "TplxError",
    "TemplateNotFound",
    "NoEngineError",
    "EngineUnavailableError",
    "RenderError",
    "UndefinedError",
    "RenderTimeoutError",
    "SandboxError",
]


class TplxError(Exception):
    """Base class of every error tplx raises."""


class TemplateNotFound(TplxError, LookupError):
    """No search path holds a file for the name, or the name escapes them.

    `names` holds every name tried, in order; `name` is the first.
    """

    def __init__(
        self, name: "Union[str, Sequence[str]]", message: "Optional[str]" = None
    ) -> None:
        self.names = (name,) if isinstance(name, str) else tuple(name)
        self.name = self.names[0]
        if message is None:
            if len(self.names) == 1:
                message = f"template not found: {self.name!r}"
            else:
                tried = ", ".join(repr(each) for each in self.names)
                message = f"none of these templates was found: {tried}"
        super().__init__(message)


class NoEngineError(TplxError):
    """No engine claims the file found, or the file is not text its engine can read."""


class EngineUnavailableError(TplxError):
    """The engine that claims a file cannot run here.

    Its library is not installed (the message names the extra) or the program
    it runs is not on `PATH` (the message names the program).
    """


class RenderError(TplxError):
    """An engine failed to compile or render a template.

    The engine's own exception is the `__cause__`; the message names the engine
    and the file.
    """


class UndefinedError(RenderError, NameError):
    """The template used a name the data does not define, in `strict` mode."""


class RenderTimeoutError(RenderError, TimeoutError):
    """A program-backed engine did not finish within its timeout."""


class SandboxError(TplxError):
    """The sandbox refused: an engine that cannot be sandboxed, or something a
    sandboxed engine does not allow (an unsafe attribute, a method call)."""
