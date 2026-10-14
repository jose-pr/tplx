"""A lazy mapping of partials, for engines that take a dict of them."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable, Dict, Iterator, Optional

from ..exceptions import TemplateNotFound


class Partials(Mapping):
    """Partials resolved through a `Lookup` the first time a template asks for one.

    A partial the including engine claims is passed to `native` with its
    source text; any other is passed to `foreign` with its name, to be
    rendered by its own engine. A name the lookup cannot find is a `KeyError`,
    unless `strict`, when the `TemplateNotFound` propagates out of the render.
    """

    def __init__(
        self,
        lookup: "Optional[Any]",
        engine: type,
        native: "Callable[[str], Any]",
        foreign: "Callable[[str], Any]",
        *,
        strict: bool = False,
    ) -> None:
        self._lookup = lookup
        self._engine = engine
        self._native = native
        self._foreign = foreign
        self._strict = strict
        self._found: Dict[str, Any] = {}

    def __getitem__(self, name: str) -> Any:
        if name in self._found:
            return self._found[name]
        if self._lookup is None:
            raise KeyError(name)
        try:
            found = self._lookup.include(name, self._engine)
        except TemplateNotFound:
            if self._strict:
                raise
            raise KeyError(name) from None
        if found.text is not None:
            value = self._native(found.text)
        else:
            value = self._foreign(name)
        self._found[name] = value
        return value

    def __contains__(self, name: object) -> bool:
        try:
            self[name]  # type: ignore[index]
        except KeyError:
            return False
        return True

    def __iter__(self) -> Iterator[str]:
        return iter(self._found)

    def __len__(self) -> int:
        return len(self._found)
