"""Liquid (`.liquid`), behind the `liquid` extra."""

from __future__ import annotations

import re
from contextvars import ContextVar
from collections import OrderedDict
from typing import Any, FrozenSet, Mapping, Optional

from .._loader import Lookup
from .._template import Template
from ..exceptions import (
    EngineUnavailableError,
    SandboxError,
    TemplateNotFound,
    UndefinedError,
)
from . import _bounds as bounds
from ._capture import CAPTURE_NAME, cached, capture, captured, capturing


def _liquid():
    try:
        import liquid
        from liquid.loader import TemplateSource
    except ImportError as exc:
        raise EngineUnavailableError(
            "the liquid template engine needs the 'liquid' extra: "
            "pip install tplx[liquid]"
        ) from exc
    return liquid, TemplateSource


#: The data of the render in progress, as given, for another engine's include;
#: kept out of the template's own names.
_VALUES: "ContextVar[Mapping[str, Any]]" = ContextVar("tplx_liquid_values")

_ENDRAW = re.compile(r"\{%-?\s*endraw\s*-?%\}")


def _raw(text: str) -> str:
    """`text` as Liquid source that renders to exactly `text`."""
    parts = []
    last = 0
    for match in _ENDRAW.finditer(text):
        parts.append(text[last : match.start()])
        parts.append("{%% endraw %%}{{ '%s' }}{%% raw %%}" % match.group(0))
        last = match.end()
    parts.append(text[last:])
    return "{% raw %}" + "".join(parts) + "{% endraw %}"


def _environment(liquid, TemplateSource, lookup, engine: type, mode: str):
    """A liquid `Environment` whose `include` and `render` tags use `lookup`."""

    class _LookupLoader(liquid.BaseLoader):
        def get_source(self, env, template_name, *, context=None, **kwargs):
            if lookup is None:
                raise liquid.exceptions.TemplateNotFoundError(template_name)
            try:
                found = lookup.include(template_name, engine)
            except TemplateNotFound as exc:
                raise liquid.exceptions.TemplateNotFoundError(template_name) from exc
            source = found.source
            if found.text is not None:
                return TemplateSource(found.text, source.origin, source.uptodate, None)
            # Another engine's file, rendered with the data of this render and
            # inserted as raw text.
            text = lookup.render_include(template_name, _VALUES.get({}))
            return TemplateSource(_raw(text), source.origin, None, None)

    undefined = {
        "strict": liquid.StrictUndefined,
        "lenient": liquid.Undefined,
        "debug": liquid.DebugUndefined,
    }[mode]
    environment = liquid.Environment(loader=_LookupLoader(), undefined=undefined)
    environment.filters[CAPTURE_NAME] = capture
    limits = lookup.loader.limits if lookup is not None else None
    if limits is not None:
        environment.output_stream_limit = limits.max_output
        environment.loop_iteration_limit = limits.max_iterations
        environment.context_depth_limit = limits.max_depth
        environment.local_namespace_limit = limits.max_output
        _bound_filters(environment, limits.max_output)
    return environment


def _bound_filters(environment: Any, limit: int) -> None:
    """Check Liquid's `replace` and `join` before they build their result."""
    filters = environment.filters
    original_replace, original_join = filters.get("replace"), filters.get("join")
    if original_replace is not None:

        def replace(value, seq, sub="", *args, **keywords):
            bounds.replace(str(value), str(seq), str(sub), -1, limit)
            return original_replace(value, seq, sub, *args, **keywords)

        filters["replace"] = replace
    if original_join is not None:

        def join(value, separator=" ", *args, **keywords):
            bounds.join(separator, value, limit)
            return original_join(value, separator, *args, **keywords)

        filters["join"] = join


class LiquidTemplate(Template):
    """A Liquid template, rendered by python-liquid. Needs the **`liquid` extra**.

    Liquid reads mappings, not attributes, so objects in the data are presented
    as read-only mappings of their attributes. `{% include %}` and
    `{% render %}` resolve through the `Lookup` that loaded the file, exactly
    as a render would: a Liquid file is parsed by Liquid, any other is rendered
    by its own engine with the render's data and its output inserted. All
    three undefined modes apply. `eval` takes a Liquid expression with its
    filters (`xs | sort`).
    """

    EXT = (".liquid",)
    _SYNTAX = re.compile(r"\{[{%]")
    _EXPRESSION = ("{{", "}}", "-", "-")
    SANDBOXED = True

    @classmethod
    def environment(cls, lookup: "Optional[Lookup]" = None) -> Any:
        """The Liquid environment `lookup`'s templates share."""
        liquid, TemplateSource = _liquid()
        mode = lookup.loader.undefined if lookup is not None else "strict"

        def factory():
            return cls.configured(
                lookup, _environment(liquid, TemplateSource, lookup, cls, mode)
            )

        if lookup is None:
            return factory()
        return lookup.state(("liquid", cls, mode), factory)

    @classmethod
    def _evaluate_expression(
        cls,
        expression: str,
        values: "Mapping[str, Any]",
        *,
        lookup: "Optional[Lookup]" = None,
    ) -> Any:
        liquid, _ = _liquid()
        environment = cls.environment(lookup)
        source = "{{ %s | %s }}" % (expression, CAPTURE_NAME)
        build = lambda: environment.from_string(source)  # noqa: E731
        if lookup is None:
            template = build()
        else:
            cache = lookup.state(("liquid-expressions", cls), OrderedDict)
            template = cached(cache, expression, build)
        encoder = lookup.loader.encoder if lookup is not None else None
        data = (
            encoder.view(values, plain=lookup.loader.sandbox)
            if encoder is not None
            else dict(values)
        )
        with capturing() as box:
            try:
                template.render(**data)
            except liquid.exceptions.UndefinedError as exc:
                raise UndefinedError(f"{expression!r}: {exc}") from exc
            except liquid.exceptions.ResourceLimitError as exc:
                raise SandboxError(f"{expression!r}: {exc}") from exc
        # An undefined name reaches the filter as Liquid's Undefined; type() so
        # a StrictUndefined is not touched.
        if box and issubclass(type(box[0]), liquid.Undefined):
            if lookup is None or lookup.loader.undefined == "strict":
                raise UndefinedError(f"{expression!r} is undefined")
            return None
        return captured(box)

    def references(self) -> FrozenSet[str]:
        return frozenset(str(name) for name in self._template.global_variables())

    def __init__(
        self,
        source: str,
        *,
        lookup: "Optional[Lookup]" = None,
        origin: str = "<string>",
    ) -> None:
        super().__init__(source, lookup=lookup, origin=origin)
        self._liquid, _ = _liquid()
        environment = type(self).environment(lookup)
        self._template = environment.from_string(source, name=origin)

    def render_values(self, values: "Mapping[str, Any]") -> str:
        token = _VALUES.set(values)
        try:
            return self._template.render(
                **self.encoder.view(values, plain=self.sandbox)
            )
        except self._liquid.exceptions.UndefinedError as exc:
            raise UndefinedError(f"{self.origin}: {exc}") from exc
        except self._liquid.exceptions.ResourceLimitError as exc:
            raise SandboxError(f"{self.origin}: {exc}") from exc
        except self._liquid.exceptions.TemplateNotFoundError as exc:
            if isinstance(exc.__cause__, TemplateNotFound):
                raise exc.__cause__ from None
            raise
        finally:
            _VALUES.reset(token)
