"""Handlebars (`.hbs`, `.handlebars`), behind the `handlebars` extra."""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any, Mapping, Optional

from .._loader import Lookup
from .._template import Template
from ..exceptions import EngineUnavailableError
from ._capture import CAPTURE_NAME, cached, capture, captured, capturing
from ._partials import Partials

LOGGER = logging.getLogger("tplx")


def _pybars():
    try:
        from pybars import Compiler
    except ImportError as exc:
        raise EngineUnavailableError(
            "the handlebars template engine needs the 'handlebars' extra: "
            "pip install tplx[handlebars]"
        ) from exc
    return Compiler


class HandlebarsTemplate(Template):
    """A Handlebars template, rendered by pybars3. Needs the **`handlebars` extra**.

    `{{> name}}` partials resolve through the `Lookup` that loaded the file,
    exactly as a render would: a Handlebars file is compiled by Handlebars, any
    other is rendered by its own engine with the template's data and its
    output inserted. Handlebars has **no strict mode**: an
    undefined name renders empty whatever the undefined mode says. A partial
    that cannot be found raises `TemplateNotFound` under `strict` and renders
    empty otherwise, as in Mustache.
    As Handlebars specifies, `{{x}}` is **HTML-escaped**; `{{{x}}}` writes the
    value as it is.
    """

    EXT = (".hbs", ".handlebars")
    SANDBOXED = True

    @classmethod
    def evaluate(
        cls,
        expression: str,
        values: "Mapping[str, Any]",
        *,
        lookup: "Optional[Lookup]" = None,
    ) -> Any:
        """A Handlebars expression (`a.b`, `helper arg`), its value's type kept."""
        source = "{{%s %s}}" % (CAPTURE_NAME, expression)
        build = lambda: _pybars()().compile(source)  # noqa: E731
        if lookup is None:
            template, helpers = build(), {}
            data = dict(values)
        else:
            cache = lookup.state(("handlebars-expressions", cls), OrderedDict)
            template = cached(cache, expression, build)
            helpers = dict(
                lookup.state(
                    ("handlebars-helpers", cls), lambda: cls.configured(lookup, {})
                )
            )
            data = lookup.loader.encoder.view(values, plain=lookup.loader.sandbox)
        helpers[CAPTURE_NAME] = lambda this, value=None, *rest, **keywords: capture(
            value
        )
        with capturing() as box:
            template(data, helpers=helpers)
        return captured(box)

    def __init__(
        self,
        source: str,
        *,
        lookup: "Optional[Lookup]" = None,
        origin: str = "<string>",
    ) -> None:
        super().__init__(source, lookup=lookup, origin=origin)
        self._compiler = _pybars()()
        self._template = self._compiler.compile(source)

    def render_values(self, values: "Mapping[str, Any]") -> str:
        if self.undefined == "strict":
            LOGGER.debug(
                "handlebars cannot fail on an undefined name; strict does not "
                "apply to %s",
                self.origin,
            )
        lookup = self.lookup

        def foreign(name):
            # pybars calls a partial with the scope and keywords and grows its
            # output by the list returned.
            return lambda *args, **kwargs: [lookup.render_include(name, values)]

        cache = (
            lookup.state(("handlebars-partials", type(self)), dict) if lookup else None
        )
        partials = Partials(
            lookup,
            type(self),
            self._compiler.compile,
            foreign,
            strict=self.undefined == "strict",
            cache=cache,
            missing=lambda *args, **kwargs: [],
        )
        # pybars returns a list of fragments, not a string.
        helpers = (
            lookup.state(("handlebars-helpers", type(self)), self._helpers)
            if lookup
            else {}
        )
        return "".join(
            self._template(
                self.encoder.view(values, plain=self.sandbox),
                helpers=helpers,
                partials=partials,
            )
        )

    def _helpers(self) -> dict:
        """The helpers every render of this lookup passes, as `configure` sets them."""
        return self.configure_native({})
