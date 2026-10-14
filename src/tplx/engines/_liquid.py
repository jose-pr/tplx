"""Liquid (`.liquid`), behind the `liquid` extra."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .._template import Template
from ..exceptions import EngineUnavailableError, TemplateNotFound, UndefinedError


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


#: The render argument carrying the data as given, for another engine's include.
VALUES_NAME = "__tplx_values__"

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
            values = context.globals.get(VALUES_NAME, {}) if context else {}
            text = lookup.render_include(template_name, values)
            return TemplateSource(_raw(text), source.origin, None, None)

    undefined = {
        "strict": liquid.StrictUndefined,
        "lenient": liquid.Undefined,
        "debug": liquid.DebugUndefined,
    }[mode]
    return liquid.Environment(loader=_LookupLoader(), undefined=undefined)


class LiquidTemplate(Template):
    """A Liquid template, rendered by python-liquid. Needs the **`liquid` extra**.

    Liquid reads mappings, not attributes, so objects in the data are presented
    as read-only mappings of their attributes. `{% include %}` and
    `{% render %}` resolve through the `Lookup` that loaded the file, exactly
    as a render would: a Liquid file is parsed by Liquid, any other is rendered
    by its own engine with the render's data and its output inserted. All three undefined modes apply.
    """

    EXT = (".liquid",)

    def __init__(self, source: str, *, lookup=None, origin: str = "<string>") -> None:
        super().__init__(source, lookup=lookup, origin=origin)
        liquid, TemplateSource = _liquid()
        self._liquid = liquid
        mode = self.undefined
        key = ("liquid", type(self), mode)

        def factory():
            return _environment(liquid, TemplateSource, lookup, type(self), mode)

        environment = lookup.state(key, factory) if lookup is not None else factory()
        self._template = environment.from_string(source, name=origin)

    def render_values(self, values: "Mapping[str, Any]") -> str:
        try:
            data = self.encoder.view(values)
            data[VALUES_NAME] = values
            return self._template.render(**data)
        except self._liquid.exceptions.UndefinedError as exc:
            raise UndefinedError(f"{self.origin}: {exc}") from exc
        except self._liquid.exceptions.TemplateNotFoundError as exc:
            if isinstance(exc.__cause__, TemplateNotFound):
                raise exc.__cause__ from None
            raise
