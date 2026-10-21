"""`tplx find`: which file a name resolves to, and which engine renders it."""

from __future__ import annotations

import typing as _ty

from duho import OutputArgs

from ._common import Command

__all__ = ["Find"]


class Find(OutputArgs, Command):
    """Show the file a template name resolves to and the engine that renders it."""

    _parsername_ = "find"
    _parseraliases_ = ["which"]

    names: _ty.List[str]
    "Template names tried in order, the first found wins; one file path when no --root is given"
    ("names",)

    def __call__(self) -> int:
        lookup, names = self.resolve(self.names)
        source, engine = lookup.resolve(names)
        self._output_(
            {"origin": source.origin, "engine": engine.__name__},
            text=f"{source.origin}\t{engine.__name__}",
        )
        return 0
