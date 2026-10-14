"""`python -m tplx`: the same program as the `tplx` console script."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
