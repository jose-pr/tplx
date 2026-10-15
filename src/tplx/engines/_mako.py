"""mako (`.mako`), behind the `mako` extra."""

from __future__ import annotations

import re
import logging
from collections import OrderedDict
from io import StringIO
from typing import Any, Mapping, Optional

from .._loader import Lookup
from .._template import Template
from ..exceptions import EngineUnavailableError, TemplateNotFound, UndefinedError
from ._capture import CAPTURE_NAME, cached, capture, captured, capturing

LOGGER = logging.getLogger("tplx")

#: The name a stub calls to render another engine's file.
INCLUDE_NAME = "__tplx_include__"

#: Names mako owns inside a template; data under one of them is dropped with a
#: warning rather than colliding with the render machinery.
RESERVED_NAMES = frozenset(
    {
        "self",
        "context",
        "capture",
        "caller",
        "loop",
        "next",
        "parent",
        "pageargs",
        "UNDEFINED",
    }
)

_BLANKS_CONTEXT = None


def _mako():
    try:
        from mako import runtime
        from mako.lookup import TemplateLookup
        from mako.template import Template as MakoTemplate
    except ImportError as exc:
        raise EngineUnavailableError(
            "the mako template engine needs the 'mako' extra: pip install tplx[mako]"
        ) from exc
    return MakoTemplate, TemplateLookup, runtime


def _blanks_context(runtime):
    """A mako `Context` whose undefined names render empty, for `lenient`.

    mako has no lenient mode: an undefined name arrives as `UNDEFINED`, which
    raises when written. Compiled templates read names through
    `context.get(name, UNDEFINED)`, so overriding `get` is the hook.
    """
    global _BLANKS_CONTEXT
    if _BLANKS_CONTEXT is None:

        class _Blanks(runtime.Context):
            def get(self, key, default=None):
                value = super().get(key, default)
                if value is runtime.UNDEFINED:
                    LOGGER.warning(
                        "mako template: %s has no value; rendering empty", key
                    )
                    return ""
                return value

        _BLANKS_CONTEXT = _Blanks
    return _BLANKS_CONTEXT


def _template_lookup(TemplateLookup, MakoTemplate, lookup, engine: type, strict: bool):
    """A mako `TemplateLookup` that resolves `file=` through `lookup`."""

    class _Lookup(TemplateLookup):
        def adjust_uri(self, uri, relativeto):
            # Names are root-relative, as in every engine: an include does not
            # move with the directory of the file that includes it.
            return uri

        def get_template(self, uri):
            cached = self._collection.get(uri)
            if cached is not None and cached[1]():
                return cached[0]
            if lookup is None:
                raise TemplateNotFound(uri)
            found = lookup.include(uri, engine)
            if found.text is not None:
                text = found.text
            else:
                # Another engine's file: a stub that renders it with this
                # template's data.
                text = "${%s(context, %r)}" % (INCLUDE_NAME, uri)
            compiled = MakoTemplate(text, lookup=self, uri=uri, **self.template_args)
            self._collection[uri] = (compiled, found.source.uptodate)
            return compiled

    return _Lookup(strict_undefined=strict)


class MakoTemplate(Template):
    """A mako template. Needs the **`mako` extra**.

    `<%include file=.../>`, `<%inherit file=.../>` and `<%namespace file=.../>`
    resolve through the `Lookup` that loaded the file, exactly as a render
    would: a mako file is compiled by mako, any other is rendered by its own
    engine with the template's data and its output inserted. Names are
    root-relative. `strict` is mako's own `strict_undefined`
    (raising `UndefinedError`); `lenient` renders an undefined name empty and
    logs it. **`debug` behaves as `lenient`**: compiled mako cannot re-emit the
    `${...}` it came from. A data name in `RESERVED_NAMES` is dropped with a
    warning.
    """

    EXT = (".mako",)
    _SYNTAX = re.compile(r"\$\{|<%|^[ \t]*(?:%|##)", re.MULTILINE)
    _EXPRESSION = ("${", "}", "", "")

    @classmethod
    def template_lookup(cls, lookup: "Optional[Lookup]" = None) -> Any:
        """The mako `TemplateLookup` `lookup`'s templates share."""
        Mako, TemplateLookup, _ = _mako()
        strict = (
            lookup.loader.undefined if lookup is not None else "strict"
        ) == "strict"

        def factory():
            return cls.configured(
                lookup, _template_lookup(TemplateLookup, Mako, lookup, cls, strict)
            )

        if lookup is None:
            return factory()
        return lookup.state(("mako", cls, strict), factory)

    @classmethod
    def _evaluate_expression(
        cls,
        expression: str,
        values: "Mapping[str, Any]",
        *,
        lookup: "Optional[Lookup]" = None,
    ) -> Any:
        """A Python expression as mako's `${...}` reads it, its value's type kept."""
        Mako, _, runtime = _mako()
        mako_lookup = cls.template_lookup(lookup)
        source = "${%s(%s)}" % (CAPTURE_NAME, expression)
        build = lambda: Mako(
            source, lookup=mako_lookup, **mako_lookup.template_args
        )  # noqa: E731
        if lookup is None:
            template = build()
        else:
            cache = lookup.state(("mako-expressions", cls), OrderedDict)
            template = cached(cache, expression, build)
        names = {k: v for k, v in values.items() if k not in RESERVED_NAMES}
        names[CAPTURE_NAME] = capture
        strict = (
            lookup.loader.undefined if lookup is not None else "strict"
        ) == "strict"
        with capturing() as box:
            if strict:
                try:
                    template.render(**names)
                except NameError as exc:
                    raise UndefinedError(f"{expression!r}: {exc}") from exc
            else:
                template.render_context(_blanks_context(runtime)(StringIO(), **names))
        return captured(box)

    def __init__(
        self,
        source: str,
        *,
        lookup: "Optional[Lookup]" = None,
        origin: str = "<string>",
    ) -> None:
        super().__init__(source, lookup=lookup, origin=origin)
        Mako, _, self._runtime = _mako()
        mako_lookup = type(self).template_lookup(lookup)
        # The lookup's template_args (strict_undefined, and whatever `configure`
        # set, such as imports or default_filters) build every template.
        self._template = Mako(
            source, lookup=mako_lookup, uri=origin, **mako_lookup.template_args
        )

    def _namespace(self, data: "Mapping[str, Any]") -> dict:
        names = {}
        for key, value in data.items():
            if key in RESERVED_NAMES:
                LOGGER.warning(
                    "mako template: %r is reserved by mako and is not available "
                    "to the template",
                    key,
                )
                continue
            names[key] = value
        lookup = self.lookup
        if lookup is not None:

            def include(context, name):
                data = {k: v for k, v in context.kwargs.items() if k != INCLUDE_NAME}
                return lookup.render_include(name, data)

            names[INCLUDE_NAME] = include
        return names

    def render_values(self, values: "Mapping[str, Any]") -> str:
        names = self._namespace(values)
        if self.undefined == "strict":
            try:
                return self._template.render(**names)
            except NameError as exc:
                raise UndefinedError(f"{self.origin}: {exc}") from exc
        buffer = StringIO()
        self._template.render_context(_blanks_context(self._runtime)(buffer, **names))
        return buffer.getvalue()
