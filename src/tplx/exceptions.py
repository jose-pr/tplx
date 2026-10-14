"""The errors tplx raises. Every one derives from `TplxError`."""

__all__ = [
    "TplxError",
    "TemplateNotFound",
    "NoEngineError",
    "EngineUnavailableError",
    "RenderError",
    "UndefinedError",
    "RenderTimeoutError",
]


class TplxError(Exception):
    """Base class of every error tplx raises."""


class TemplateNotFound(TplxError, LookupError):
    """No search path holds a file for the name, or the name escapes them."""

    def __init__(self, name: str, message: "str | None" = None) -> None:
        self.name = name
        super().__init__(message or f"template not found: {name!r}")


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
