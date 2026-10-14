"""`python -m tplx`: the same program as the `tplx` console script."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
