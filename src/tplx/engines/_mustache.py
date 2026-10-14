"""Mustache (`.mustache`), behind the `mustache` extra."""

from __future__ import annotations

from typing import Any, Mapping

from .._template import Template
from ..exceptions import EngineUnavailableError
from ._partials import Partials


def _chevron():
    try:
        import chevron
    except ImportError as exc:
        raise EngineUnavailableError(
            "the mustache template engine needs the 'mustache' extra: "
            "pip install tplx[mustache]"
        ) from exc
    return chevron


#: A Mustache set-delimiter tag switching to two control characters.
RAW_DELIMITERS = "{{=\x01 \x02=}}"


class MustacheTemplate(Template):
    """A Mustache template, rendered by chevron. Needs the **`mustache` extra**.

    `{{> name}}` partials resolve through the `Lookup` that loaded the file,
    exactly as a render would: a Mustache file is parsed by Mustache, any other
    is rendered by its own engine with the template's data and its output
    inserted. Under `strict` a partial that cannot be
    found raises `TemplateNotFound`, otherwise it renders empty. chevron has
    **no strict mode for names**: an undefined name renders empty, and under
    `strict` chevron's own warning is turned on so it reaches the log.
    """

    EXT = (".mustache",)

    def __init__(self, source: str, *, lookup=None, origin: str = "<string>") -> None:
        super().__init__(source, lookup=lookup, origin=origin)
        self._chevron = _chevron()

    def render_values(self, values: "Mapping[str, Any]") -> str:
        strict = self.undefined == "strict"
        lookup = self.lookup

        def foreign(name):
            # Delimiters no output contains, so chevron inserts the text as is;
            # a delimiter change applies only inside the partial.
            return RAW_DELIMITERS + lookup.render_include(name, values)

        partials = Partials(lookup, type(self), str, foreign, strict=strict)
        return self._chevron.render(
            self.source,
            self.encoder.view(values),
            partials_path=None,
            partials_dict=partials,
            warn=strict,
        )
