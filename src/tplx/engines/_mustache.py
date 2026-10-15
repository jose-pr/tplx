"""Mustache (`.mustache`), behind the `mustache` extra."""

from __future__ import annotations

import re
import logging
from collections.abc import Mapping as _Mapping
from typing import Any, FrozenSet, Mapping, Optional

from .._loader import Lookup
from .._template import Template
from .._encoder import unwrap
from ..exceptions import EngineUnavailableError, UndefinedError
from ._partials import Partials

LOGGER = logging.getLogger("tplx")


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
    **no strict mode for names**: an undefined name renders empty whatever the
    undefined mode says.
    As Mustache specifies, `{{x}}` is **HTML-escaped**; `{{{x}}}` or `{{& x}}`
    writes the value as it is.
    """

    EXT = (".mustache",)
    _SYNTAX = re.compile(r"\{\{")
    _EXPRESSION = ("{{", "}}", "{&", "}")
    SANDBOXED = True

    @classmethod
    def evaluate_expression(
        cls,
        expression: str,
        values: "Mapping[str, Any]",
        *,
        lookup: "Optional[Lookup]" = None,
    ) -> Any:
        """A Mustache name (`a.b`, `.` for the whole data): the value it names."""
        current: Any = (
            lookup.loader.encoder.view(values, plain=lookup.loader.sandbox)
            if lookup is not None
            else dict(values)
        )
        path = expression.strip()
        if path != ".":
            for part in path.split("."):
                if isinstance(current, _Mapping) and part in current:
                    current = current[part]
                    continue
                if lookup is None or lookup.loader.undefined == "strict":
                    raise UndefinedError(f"{expression!r}: {part!r} is undefined")
                return None
        return unwrap(current)

    def references(self) -> FrozenSet[str]:
        names = set()
        depth = 0
        for tag, key in self._chevron.tokenizer.tokenize(self.source):
            if tag in ("variable", "no escape", "section", "inverted section"):
                if depth == 0 and key != ".":
                    names.add(key.split(".")[0])
            if tag in ("section", "inverted section"):
                depth += 1
            elif tag == "end":
                depth -= 1
        return frozenset(names)

    def __init__(
        self,
        source: str,
        *,
        lookup: "Optional[Lookup]" = None,
        origin: str = "<string>",
    ) -> None:
        super().__init__(source, lookup=lookup, origin=origin)
        self._chevron = _chevron()

    def render_values(self, values: "Mapping[str, Any]") -> str:
        strict = self.undefined == "strict"
        lookup = self.lookup

        def foreign(name):
            # Delimiters no output contains, so chevron inserts the text as is;
            # a delimiter change applies only inside the partial.
            return RAW_DELIMITERS + lookup.render_include(name, values)

        if strict:
            LOGGER.debug(
                "mustache cannot fail on an undefined name; strict does not "
                "apply to %s",
                self.origin,
            )
        cache = (
            lookup.state(("mustache-partials", type(self)), dict) if lookup else None
        )
        partials = Partials(
            lookup, type(self), str, foreign, strict=strict, cache=cache
        )
        return self._chevron.render(
            self.source,
            self.encoder.view(values, plain=self.sandbox),
            partials_path=None,
            partials_dict=partials,
        )
