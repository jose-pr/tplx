"""Go `text/template` (`.tmpl`, `.gotmpl`), behind the `go` extra (gotpl)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Callable, Dict, List, Optional, Tuple

from .._loader import Lookup
from .._template import Template
from ..exceptions import (
    EngineUnavailableError,
    TemplateNotFound,
    TplxError,
    UndefinedError,
)

#: The function a stub calls to render another engine's file.
INCLUDE_FUNCTION = "tplxInclude"
#: The function a stub calls for a template name nothing defines or finds.
MISSING_FUNCTION = "tplxMissing"

#: tplx's undefined modes as gotpl's `missing_key`. Go has no mode that writes
#: an empty string for a missing map key: `zero` and `default` both write
#: `<no value>`.
_MISSING_KEY = {"strict": "error", "lenient": "default", "debug": "default"}


def _gotpl():
    try:
        import gotpl
    except ImportError as exc:
        raise EngineUnavailableError(
            "the go template engine needs the 'go' extra, on Python 3.11 or "
            "later: pip install tplx[go]"
        ) from exc
    return gotpl


def _name_pattern(delimiters: Tuple[str, str], actions: str) -> "re.Pattern[str]":
    """Template names after `actions` (`template|block`) in an action."""
    return re.compile(
        re.escape(delimiters[0])
        + rf"-?\s*(?:{actions})\s+(?:\"((?:[^\"\\]|\\.)*)\"|`([^`]*)`)"
    )


def _names(pattern: "re.Pattern[str]", text: str) -> List[str]:
    found = []
    for match in pattern.finditer(text):
        quoted, raw = match.groups()
        found.append(json.loads(f'"{quoted}"') if quoted is not None else raw)
    return found


class GoTemplate(Template):
    """A Go `text/template` template, rendered by gotpl. Needs the **`go` extra**
    (Python 3.11 or later).

    The data is passed as it is: `.Name` reads a key or an attribute. Go's
    builtin functions only; `Loader(configure={GoTemplate: function})` receives
    the dict of functions, so Sprig is
    `functions.update(gotpl.funcs.sprig.text_func_map())`.

    `{{template "name" .}}` and `{{block}}` names that the file does not
    `define` resolve through the `Lookup` that loaded it, exactly as a render
    would: a Go file joins the template set, any other is rendered by its own
    engine with the pipeline's data (a mapping, or nothing) and its output
    inserted. A name found nowhere raises `TemplateNotFound` when it executes
    under `strict` and renders empty otherwise. `strict` raises a missing key
    as `UndefinedError`; Go has no empty mode, so `lenient` and `debug` both
    write `<no value>`. Output keeps the template's text as it is.
    """

    EXT = (".tmpl", ".gotmpl")
    #: The action delimiters, as Go's `Delims`.
    DELIMITERS: Tuple[str, str] = ("{{", "}}")

    def __init__(
        self,
        source: str,
        *,
        lookup: "Optional[Lookup]" = None,
        origin: str = "<string>",
    ) -> None:
        super().__init__(source, lookup=lookup, origin=origin)
        self._gotpl = gotpl = _gotpl()
        functions: Dict[str, Callable[..., Any]] = (
            dict(lookup.state(("go-functions", type(self)), self._functions))
            if lookup is not None
            else {}
        )
        functions[INCLUDE_FUNCTION] = self._include
        functions[MISSING_FUNCTION] = self._missing
        self._checks: List[Callable[[], bool]] = []
        sources = {origin: source}
        self._collect(source, sources)
        environment = gotpl.Environment(
            functions=functions,
            delimiters=self.DELIMITERS,
            missing_key=_MISSING_KEY[self.undefined],
        )
        self._root = origin
        self._engine = environment.from_sources(sources)

    def _functions(self) -> Dict[str, Callable[..., Any]]:
        """The functions every template of this lookup has, as `configure` sets them."""
        return self.configure_native({})

    def _stub(self, function: str, name: str, data: str = "") -> str:
        left, right = self.DELIMITERS
        return f"{left}{function} {json.dumps(name)}{data}{right}"

    def _collect(self, text: str, sources: Dict[str, str]) -> None:
        """Add to `sources` every template `text` uses that the set does not define."""
        defined = _name_pattern(self.DELIMITERS, "define|block")
        used = _name_pattern(self.DELIMITERS, "template|block")
        names = {name for each in sources.values() for name in _names(defined, each)}
        for name in _names(used, text):
            if name in names or name in sources:
                continue
            if self.lookup is None:
                sources[name] = self._stub(MISSING_FUNCTION, name)
                continue
            try:
                found = self.lookup.include(name, type(self))
            except TemplateNotFound:
                sources[name] = self._stub(MISSING_FUNCTION, name)
                continue
            self._checks.append(found.source.uptodate)
            if found.text is None:
                sources[name] = self._stub(INCLUDE_FUNCTION, name, " .")
                continue
            sources[name] = found.text
            self._collect(found.text, sources)
            names.update(_names(defined, found.text))

    def _include(self, name: str, data: Any = None) -> str:
        values = data if isinstance(data, Mapping) else {}
        return self.lookup.render_include(name, values)

    def _missing(self, name: str) -> str:
        if self.undefined == "strict":
            raise TemplateNotFound(name)
        return ""

    @property
    def is_up_to_date(self) -> bool:
        """Is the file unchanged, and every file it includes?"""
        return super().is_up_to_date and all(check() for check in self._checks)

    def render_values(self, values: "Mapping[str, Any]") -> str:
        gotpl = self._gotpl
        try:
            return self._engine.render_template(self._root, dict(values))
        except gotpl.TemplateExecutionError as exc:
            cause = exc.__cause__
            if isinstance(cause, TplxError):
                raise cause from None
            if "missing key" in str(exc):
                raise UndefinedError(f"{self.origin}: {exc}") from exc
            raise
