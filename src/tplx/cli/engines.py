"""`tplx engines`: the registered engines, in the order they are consulted."""

from __future__ import annotations

from duho import Cmd, OutputArgs

from .._registry import registered_engines, template_extensions

__all__ = ["Engines"]


class Engines(OutputArgs, Cmd):
    """List the registered engines, highest priority first, with their suffixes."""

    _parsername_ = "engines"

    def __call__(self) -> int:
        rows = [
            {
                "engine": cls.__name__,
                "suffixes": list(template_extensions(cls) or ["*"]),
                "priority": int(cls.PRIORITY),
            }
            for cls in registered_engines()
        ]
        self._output_(
            rows,
            text=lambda rows: "\n".join(
                f"{row['engine']}\t{' '.join(row['suffixes'])}\t{row['priority']}"
                for row in rows
            ),
        )
        return 0
