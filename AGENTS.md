# tplx — working in this checkout

| Shipped header | Covers |
| --- | --- |
| [`src/tplx/AGENTS.md`](src/tplx/AGENTS.md) | the public API; it ships in the wheel |

## Layout

| Path | What |
| ---- | ---- |
| `src/tplx/` | the package |
| `src/tplx/engines/` | one private module per engine |
| `src/tplx/cli/` | the `tplx` command, one module per subcommand |
| `tests/` | pytest suite |
| `docs/` + `mkdocs.yml` | the documentation site |

## Environment

Per-version venvs, gitignored: `.venv/<version>-<os>-<arch>/`. Develop on the
latest Python and also run the floor from `requires-python` (3.9) before
finishing a chunk of work.

```sh
python -m venv .venv/3.14-nt-arm64
.venv/3.14-nt-arm64/Scripts/python -m pip install -e ".[dev,docs]"   # dev pulls in every engine and the cli
```

## Checks

```sh
<venv>/python -m pytest -q -rs                 # the suite (skips are visible)
<venv>/python -m black src tests               # formatter; run before committing
<venv>/python -m mkdocs build --strict         # docs must build clean
<venv>/python -m build                         # sdist + wheel
```

## Conventions

LF everywhere, enforced by `.gitattributes` (`* text=auto eol=lf`).
Warnings are errors in the test run (`filterwarnings = ["error"]`).

## Releasing

Three workflows: `test.yml` (`workflow_dispatch` and `ci-*` tags),
`release.yml` (`v*` tags: test, floors, build, wheel smoke, docs gate, GitHub
release, PyPI) and `docs.yml` (every Pages deploy). Bump `version` in the same
commit as the `CHANGELOG.md` entry; the release body is scraped from the
matching `## [x.y.z]` section.
