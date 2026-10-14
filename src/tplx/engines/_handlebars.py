"""Handlebars (`.hbs`, `.handlebars`), behind the `handlebars` extra."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from .._template import Template
from ..exceptions import EngineUnavailableError
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
    undefined name renders empty whatever the undefined mode says.
    As Handlebars specifies, `{{x}}` is **HTML-escaped**; `{{{x}}}` writes the
    value as it is.
    """

    EXT = (".hbs", ".handlebars")

    def __init__(self, source: str, *, lookup=None, origin: str = "<string>") -> None:
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

        partials = Partials(lookup, type(self), self._compiler.compile, foreign)
        # pybars returns a list of fragments, not a string.
        return "".join(self._template(self.encoder.view(values), partials=partials))
