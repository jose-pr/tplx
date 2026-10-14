"""`tplx find`: which file a name resolves to, and which engine renders it."""

from __future__ import annotations

import json

from ._common import Command


class Find(Command):
    """Show the file a template name resolves to and the engine that renders it."""

    _parsername_ = "find"
    _parseraliases_ = ["which"]

    name: str
    "A template name looked up in the roots, or a file path when no --root is given"
    ("name",)

    json_out: bool = False
    "Print a JSON object instead of tab-separated text"
    ("--json",)

    def __call__(self) -> int:
        lookup, name = self.resolve(self.name)
        source, engine = lookup.resolve(name)
        if self.json_out:
            print(json.dumps({"origin": source.origin, "engine": engine.__name__}))
        else:
            print(f"{source.origin}\t{engine.__name__}")
        return 0
