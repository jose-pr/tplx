"""Go `text/template` (`.tmpl`, `.gotmpl`), behind the `go` extra (gotpl)."""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any, Callable, Dict, List, Optional, Tuple

from .._loader import Lookup
from .._template import Template
from . import _bounds as bounds
from ._capture import CAPTURE_NAME, cached, capture, captured, capturing
from ..exceptions import (
    EngineUnavailableError,
    SandboxError,
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
    SANDBOXED = True
    #: The action delimiters, as Go's `Delims`.
    DELIMITERS: Tuple[str, str] = ("{{", "}}")
    MARKERS = ("{{",)
    EXPRESSION = ("{{", "}}")

    def __init_subclass__(cls, **keywords: Any) -> None:
        super().__init_subclass__(**keywords)
        # A subclass with other delimiters has other markers, unless it says.
        if "MARKERS" not in cls.__dict__:
            cls.MARKERS = (cls.DELIMITERS[0],)
        if "EXPRESSION" not in cls.__dict__:
            cls.EXPRESSION = tuple(cls.DELIMITERS)  # type: ignore[assignment]

    @classmethod
    def _environment(
        cls, lookup: "Optional[Lookup]", functions: Dict[str, Callable[..., Any]]
    ) -> Any:
        """A gotpl environment with `functions`; in a sandbox, a policy that
        allows those functions and no attribute or method of an object."""
        gotpl = _gotpl()
        mode = lookup.loader.undefined if lookup is not None else "strict"
        sandbox = None
        limits = lookup.loader.limits if lookup is not None else None
        if limits is not None:
            functions = dict(functions)
            functions["printf"] = _bounded_printf(gotpl, limits.max_output)
            sandbox = gotpl.SandboxPolicy(
                allow_functions=functions,
                default_budget=gotpl.ExecutionBudget(
                    max_output_chars=limits.max_output,
                    max_iterations=limits.max_iterations,
                    max_template_depth=limits.max_depth,
                    max_function_calls=limits.max_iterations,
                ),
            )
        return gotpl.Environment(
            functions=functions,
            delimiters=cls.DELIMITERS,
            missing_key=_MISSING_KEY[mode],
            sandbox=sandbox,
        )

    @classmethod
    def _data(cls, lookup: "Optional[Lookup]", values: "Mapping[str, Any]") -> Any:
        """The data as gotpl reads it: in a sandbox, through `DataView`, which
        has no methods to call."""
        if lookup is not None and lookup.loader.sandbox:
            return lookup.loader.encoder.view(values, plain=True)
        return dict(values)

    @classmethod
    def evaluate(
        cls,
        expression: str,
        values: "Mapping[str, Any]",
        *,
        lookup: "Optional[Lookup]" = None,
    ) -> Any:
        """A Go pipeline (`.a.b`, `index .m "k"`, `printf "%d" .n`), its value's type kept."""
        gotpl = _gotpl()
        left, right = cls.DELIMITERS
        source = f"{left}{CAPTURE_NAME} ({expression}){right}"

        def build() -> Any:
            functions = (
                dict(
                    lookup.state(
                        ("go-functions", cls), lambda: cls.configured(lookup, {})
                    )
                )
                if lookup is not None
                else {}
            )
            functions[CAPTURE_NAME] = capture
            return cls._environment(lookup, functions).from_string(source)

        if lookup is None:
            template = build()
        else:
            cache = lookup.state(("go-expressions", cls), OrderedDict)
            template = cached(cache, expression, build)
        with capturing() as box:
            try:
                template.render(cls._data(lookup, values))
            except gotpl.TemplateExecutionError as exc:
                _translate(gotpl, exc, repr(expression))
                raise
        return captured(box)

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
        environment = type(self)._environment(lookup, functions)
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
            return self._engine.render_template(
                self._root, type(self)._data(self.lookup, values)
            )
        except gotpl.TemplateExecutionError as exc:
            _translate(gotpl, exc, self.origin)
            raise


def _bounded_printf(gotpl: Any, limit: int) -> Callable[..., str]:
    """Go's `printf`, refusing a width or precision past `limit` before it runs."""
    from gotpl.runtime.sync_vm import _printf

    def printf(format_string: Any, *values: Any) -> str:
        bounds.format_widths(format_string, values, limit)
        return bounds.checked(_printf(format_string, *values, format_mode="go"), limit)

    return printf


def _translate(gotpl: Any, exc: Exception, where: str) -> None:
    """Raise gotpl's execution error as tplx's: a tplx error it carries, a
    sandbox refusal, a missing key under `strict`; return for anything else."""
    cause = exc.__cause__
    if isinstance(cause, TplxError):
        raise cause from None
    if isinstance(exc, (gotpl.SandboxViolationError, gotpl.BudgetExceededError)):
        raise SandboxError(f"{where}: {exc}") from exc
    if "missing key" in str(exc):
        raise UndefinedError(f"{where}: {exc}") from exc
