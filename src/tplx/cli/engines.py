"""`tplx engines`: the registered engines, in the order they are consulted."""

from __future__ import annotations

import json

from duho import Cmd

from .._registry import registered_engines, template_extensions

__all__ = ["Engines"]


class Engines(Cmd):
    """List the registered engines, highest priority first, with their suffixes."""

    _parsername_ = "engines"

    json_out: bool = False
    "Print a JSON array instead of tab-separated text"
    ("--json",)

    def __call__(self) -> int:
        rows = [
            {
                "engine": cls.__name__,
                "suffixes": list(template_extensions(cls) or ["*"]),
                "priority": int(cls.PRIORITY),
            }
            for cls in registered_engines()
        ]
        if self.json_out:
            print(json.dumps(rows))
        else:
            for row in rows:
                print(
                    f"{row['engine']}\t{' '.join(row['suffixes'])}\t{row['priority']}"
                )
        return 0
