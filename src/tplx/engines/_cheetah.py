"""Cheetah (`.cheetah`), behind the `cheetah` extra (CT3)."""

from __future__ import annotations

from collections import OrderedDict
from contextvars import ContextVar
from typing import Any, Dict, Mapping, Optional, Tuple

from .._loader import Lookup
from .._template import Template
from ..exceptions import EngineUnavailableError, TemplateNotFound, UndefinedError
from ._capture import CAPTURE_NAME, cached, capture, captured, capturing

#: The data of the render in progress, for another engine's `#include`.
_VALUES: "ContextVar[Mapping[str, Any]]" = ContextVar("tplx_cheetah_values")

#: The `#errorCatcher` each undefined mode puts before every source: none
#: (an undefined name raises), one that renders it empty, Cheetah's `Echo`
#: (it is written back as `$name`).
_CATCHERS = {"strict": None, "lenient": "TplxBlank", "debug": "Echo"}


def _cheetah():
    try:
        from Cheetah import ErrorCatchers
        from Cheetah.NameMapper import NotFound
        from Cheetah.Template import Template as Cheetah
    except ImportError as exc:
        raise EngineUnavailableError(
            "the cheetah template engine needs the 'cheetah' extra: "
            "pip install tplx[cheetah]"
        ) from exc
    return Cheetah, ErrorCatchers, NotFound


def _bridge(
    lookup: "Optional[Lookup]", engine: type, mode: str, settings: Dict[str, Any]
) -> Tuple[type, str]:
    """A Cheetah base class whose `#include` resolves through `lookup`, and the
    prefix every source it compiles starts with."""
    Cheetah, ErrorCatchers, _ = _cheetah()
    catcher = _CATCHERS[mode]
    # On a line of its own, so a directive on the template's first line still
    # takes its line ending, as it does with no catcher.
    prefix = f"#errorCatcher {catcher}\n" if catcher else ""

    class _Blank(ErrorCatchers.ErrorCatcher):
        def warn(self, exc_val=None, code=None, rawCode=None, lineCol=None):
            return ""

    class _Bridge(Cheetah):
        # tplx caches compiled templates; Cheetah's own process-wide cache
        # would keep every lookup alive.
        _CHEETAH_cacheCompilationResults = False
        _CHEETAH_useCompilationCache = False
        _CHEETAH_keepRefToGeneratedCode = False
        _CHEETAH_compilerSettings = dict(settings)

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._CHEETAH__errorCatchers["TplxBlank"] = _Blank(self)

        def _handleCheetahInclude(
            self, srcArg, trans=None, includeFrom="file", raw=False
        ):
            if includeFrom == "file" and isinstance(srcArg, str):
                srcArg, raw = _resolve(srcArg, raw)
                if raw:
                    # Written here: Cheetah caches an include by its source,
                    # which a raw and a parsed include of one file share.
                    trans.response().write(srcArg)
                    return None
                includeFrom = "str"
            return Cheetah._handleCheetahInclude(
                self, srcArg, trans=trans, includeFrom=includeFrom, raw=raw
            )

        def _getTemplateAPIClassForIncludeDirectiveCompilation(self, source, file):
            return _Bridge

    _Bridge._CHEETAH_defaultBaseclassForTemplates = _Bridge

    def _resolve(name: str, raw: bool) -> Tuple[str, bool]:
        """`#include "name"` as Cheetah source (or raw text) and its `raw` flag."""
        try:
            if lookup is None:
                raise TemplateNotFound(name)
            found = lookup.include(name, engine)
        except TemplateNotFound:
            if mode == "strict":
                raise
            return "", True
        if found.text is not None:
            return (found.text, True) if raw else (prefix + found.text, False)
        return lookup.render_include(name, _VALUES.get({})), True

    return _Bridge, prefix


class CheetahTemplate(Template):
    """A Cheetah template, rendered by CT3. Needs the **`cheetah` extra**.

    The data is the template's search list, as it is: `$target.hostname` reads
    a key or an attribute. `#include "name"` resolves through the `Lookup` that
    loaded the file, exactly as a render would: a Cheetah file is compiled by
    Cheetah (`#include raw` inserts its text as it is), any other is rendered by
    its own engine with the render's data and its output inserted; a name
    found nowhere raises `TemplateNotFound` under `strict` and renders empty
    otherwise. `strict` raises an undefined name as `UndefinedError`, `lenient`
    renders it empty and `debug` writes it back as `$name`.
    `Loader(configure={CheetahTemplate: function})` receives the dict of
    Cheetah compiler settings.
    """

    EXT = (".cheetah",)

    @classmethod
    def bridge(cls, lookup: "Optional[Lookup]" = None) -> Tuple[type, str]:
        """The Cheetah base class `lookup`'s templates compile with, and its prefix."""
        mode = lookup.loader.undefined if lookup is not None else "strict"

        def factory() -> Tuple[type, str]:
            return _bridge(lookup, cls, mode, cls.configured(lookup, {}))

        if lookup is None:
            return factory()
        return lookup.state(("cheetah", cls, mode), factory)

    @classmethod
    def evaluate(
        cls,
        expression: str,
        values: "Mapping[str, Any]",
        *,
        lookup: "Optional[Lookup]" = None,
    ) -> Any:
        """A Cheetah expression (`$a.b * 2`), its value's type kept."""
        _, _, not_found = _cheetah()
        bridge, prefix = cls.bridge(lookup)
        source = "%s$%s(%s)" % (prefix, CAPTURE_NAME, expression)
        build = lambda: bridge.compile(source=source)  # noqa: E731
        if lookup is None:
            compiled = build()
        else:
            cache = lookup.state(("cheetah-expressions", cls), OrderedDict)
            compiled = cached(cache, expression, build)
        names = dict(values)
        names[CAPTURE_NAME] = capture
        with capturing() as box:
            try:
                str(compiled(searchList=[names]))
            except not_found as exc:
                raise UndefinedError(f"{expression!r}: {exc}") from exc
        return captured(box)

    def __init__(
        self,
        source: str,
        *,
        lookup: "Optional[Lookup]" = None,
        origin: str = "<string>",
    ) -> None:
        super().__init__(source, lookup=lookup, origin=origin)
        _, _, self._not_found = _cheetah()
        bridge, prefix = type(self).bridge(lookup)
        self._class = bridge.compile(source=prefix + source)

    def render_values(self, values: "Mapping[str, Any]") -> str:
        token = _VALUES.set(values)
        try:
            return str(self._class(searchList=[dict(values)]))
        except self._not_found as exc:
            raise UndefinedError(f"{self.origin}: {exc}") from exc
        finally:
            _VALUES.reset(token)
