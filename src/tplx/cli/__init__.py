"""The `tplx` command line, built on `duho`.

`main` is the entry point of the `tplx` console script and of `python -m tplx`.
It needs the `cli` extra (`pip install tplx[cli]`); importing this package
does not, so a bare install gets one line naming the extra instead of an
`ImportError`.
"""

from __future__ import annotations

from typing import Optional, Sequence

__all__ = ["main"]

#: What a user who ran the console script without the extra needs to be told.
_NEEDS_EXTRA = "tplx: the command line needs the 'cli' extra -- pip install 'tplx[cli]'"


def main(argv: "Optional[Sequence[str]]" = None) -> int:
    """Run the command line and return its exit status.

    `0` done, `1` the operation failed (no such template, an engine error),
    `2` the invocation was wrong, `130` Ctrl-C. A usage error, `--help` and
    `--version` from the parser raise `SystemExit`. A closed standard output
    ends silently with `1`.
    """
    try:
        import duho
    except ImportError as exc:
        raise SystemExit(_NEEDS_EXTRA) from exc

    from ._root import Tplx

    return duho.run(Tplx, argv, exit="parse")
