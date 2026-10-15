"""The engine contract every template class implements."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    FrozenSet,
    Mapping,
    Optional,
    Tuple,
    Union,
)

from ._encoder import DataEncoder
from ._registry import DEFAULT_PRIORITY, template_extensions
from .exceptions import RenderError, TplxError

_DEFAULT_ENCODER = DataEncoder()

if TYPE_CHECKING:
    from ._loader import Lookup
else:
    # `_loader` imports this module, so it sets `Lookup` here once it defines
    # it; the hints in this module then resolve at run time.
    Lookup = None

#: How a template variable with no value renders: `strict` raises
#: `UndefinedError`, `lenient` renders an empty string, `debug` leaves the
#: placeholder in the output. An engine that cannot honour a mode says so in
#: its docstring.
UNDEFINED_MODES = ("strict", "lenient", "debug")


def can_process_suffix(cls: type, file: Any) -> bool:
    """Is `file`'s suffix one `cls.EXT` claims? `file` is a path or a file name."""
    suffixes = template_extensions(cls)
    if suffixes is None:
        return True
    if isinstance(file, str):
        file = PurePosixPath(file)
    return str(getattr(file, "suffix", "")).lower() in suffixes


class Template:
    """A template an engine has compiled, ready to render.

    A subclass sets `EXT` (the suffixes it claims), optionally `PRIORITY` and
    `BINARY`, and implements `render_values`. The loader builds it with the file's
    contents, the `Lookup` that found it and the file's origin; an engine with
    an include syntax resolves includes through `self.lookup`, so they search
    the same roots as the file that includes them.
    """

    #: Suffixes this engine claims: `()` none, `None` (or `"*"`) every one.
    EXT: ClassVar[Union[None, str, Tuple[str, ...]]] = ()
    #: Engines are consulted highest first; see `DEFAULT_PRIORITY` and
    #: `FALLBACK_PRIORITY`.
    PRIORITY: ClassVar[int] = DEFAULT_PRIORITY
    #: True to receive the file's raw `bytes` and return `bytes`; False to
    #: receive UTF-8-decoded text.
    BINARY: ClassVar[bool] = False
    #: True when a template cannot reach beyond the data it is given, so a
    #: `Loader(sandbox=True)` may use this engine for untrusted templates.
    SANDBOXED: ClassVar[bool] = False
    #: What finds this engine's syntax in a text (`is_template`); None when it
    #: is not known, so every text may hold some.
    _SYNTAX: ClassVar[Optional["re.Pattern[str]"]] = None
    #: One bare expression: its opening and closing delimiters, and the
    #: whitespace-control characters each may carry (`("{{", "}}", "-", "-")`).
    _EXPRESSION: ClassVar[Optional[Tuple[str, str, str, str]]] = None

    @classmethod
    def is_template(cls, text: str) -> bool:
        """Could `text` hold this engine's syntax? False means it is plain text.

        A cheap test that compiles nothing: a True may still turn out plain.
        An engine that does not say how to tell answers True; a plugin engine
        overrides this to say.
        """
        pattern = cls._SYNTAX
        return pattern is None or pattern.search(text) is not None

    @classmethod
    def _bare_expression(cls, text: str) -> Optional[str]:
        """The expression when `text` is exactly one (`"{{ a.b }}"` is `"a.b"`), else None."""
        spec = cls._EXPRESSION
        if spec is None:
            return None
        pattern = cls.__dict__.get("_expression_pattern")
        if pattern is None:
            opening, closing, before, after = spec
            pattern = re.compile(
                r"\s*"
                + re.escape(opening)
                + (f"[{re.escape(before)}]*" if before else "")
                + r"(?P<expression>.*?)"
                + (f"[{re.escape(after)}]*" if after else "")
                + re.escape(closing)
                + r"\s*",
                re.DOTALL,
            )
            cls._expression_pattern = pattern
        found = pattern.fullmatch(text)
        if found is None:
            return None
        inner = found.group("expression").strip()
        if not inner or spec[0] in inner or spec[1] in inner:
            return None
        return inner

    def __init__(
        self,
        source: "Union[str, bytes]",
        *,
        lookup: "Optional[Lookup]" = None,
        origin: str = "<string>",
    ) -> None:
        self.source = source
        self.lookup = lookup
        self.origin = origin
        self._uptodate: "Optional[Callable[[], bool]]" = None

    @property
    def undefined(self) -> str:
        """The `UNDEFINED_MODES` entry this template renders with."""
        return self.lookup.loader.undefined if self.lookup is not None else "strict"

    @property
    def sandbox(self) -> bool:
        """Does this template render in a sandbox (its loader's `sandbox`)?"""
        return self.lookup is not None and self.lookup.loader.sandbox

    @property
    def encoder(self) -> "DataEncoder":
        """The `DataEncoder` this template presents its data with."""
        if self.lookup is not None:
            return self.lookup.loader.encoder
        return _DEFAULT_ENCODER

    def configure_native(self, native: Any) -> Any:
        """Apply the loader's `configure` functions for this engine to `native`.

        An engine calls it once, where it builds its own environment for a
        lookup; every function whose key is this engine's class or a base of it
        runs, in the order given. Returns `native`.
        """
        return type(self).configured(self.lookup, native)

    @classmethod
    def configured(cls, lookup: "Optional[Lookup]", native: Any) -> Any:
        """`configure_native` for a class: what `evaluate` uses without an instance."""
        if lookup is not None:
            for key, function in lookup.loader.configure.items():
                if issubclass(cls, key):
                    function(native)
        return native

    @property
    def is_up_to_date(self) -> bool:
        """Is the file this was loaded from unchanged? True when there is no file."""
        check = self._uptodate
        return check() if check is not None else True

    def render(
        self, data: "Optional[Mapping[str, Any]]" = None, /, **overrides: Any
    ) -> "Union[str, bytes]":
        """Render with `data`, then `overrides`, as the template's top-level names.

        A keyword wins over the same name in `data`. An engine's own exception
        is raised as `RenderError`, with it as the `__cause__`.
        """
        values = dict(data or {})
        values.update(overrides)
        try:
            return self.render_values(values)
        except TplxError:
            raise
        except Exception as exc:
            raise RenderError(
                f"{type(self).__name__} failed to render {self.origin}: {exc}"
            ) from exc

    def render_values(self, values: "Mapping[str, Any]") -> "Union[str, bytes]":
        """What an engine implements: render with `values` as the top-level names."""
        raise NotImplementedError

    @classmethod
    def evaluate(
        cls,
        expression: str,
        values: "Mapping[str, Any]",
        *,
        lookup: "Optional[Lookup]" = None,
    ) -> Any:
        """The value of `expression`, in this engine's own syntax, over `values`.

        The value keeps its type (`a.b * 2` is `42`, not `"42"`). `lookup`
        brings the loader's undefined mode, sandbox and `configure`.

        :raises NotImplementedError: this engine has no expressions.
        """
        raise NotImplementedError(f"{cls.__name__} cannot evaluate an expression")

    def references(self) -> FrozenSet[str]:
        """The top-level names this template reads from its data.

        :raises NotImplementedError: this engine cannot tell.
        """
        raise NotImplementedError(f"{type(self).__name__} cannot list its references")

    @classmethod
    def can_process(cls, file: Any, source: "Union[str, bytes]") -> bool:
        """Does this engine render `file`? By default, when it claims the suffix."""
        return can_process_suffix(cls, file)
