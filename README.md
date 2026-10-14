# tplx

[![Version](https://img.shields.io/pypi/v/tplx.svg)](https://pypi.org/project/tplx/)
[![Python versions](https://img.shields.io/pypi/pyversions/tplx.svg)](https://pypi.org/project/tplx/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/jose-pr/tplx/blob/main/LICENSE)
[![Docs](https://img.shields.io/badge/docs-latest-blue.svg)](https://jose-pr.github.io/tplx/)
[![CI](https://img.shields.io/github/actions/workflow/status/jose-pr/tplx/test.yml)](https://github.com/jose-pr/tplx/actions/workflows/test.yml)

Render a tree of templates where **each file's suffix picks its engine and its
stem names what it renders**: `boot.cfg.j2` is Jinja, `boot.cfg.mako` is mako,
and both answer to `boot.cfg`. A file no engine claims is copied byte for byte.
Documentation: <https://jose-pr.github.io/tplx/>.

## Features

- **One call for every engine** — Jinja, mako, Liquid, Handlebars, Mustache,
  ERB, EPP and a `%{NAME}` shell-style engine, each rendering the same data.
- **Name by stem, dispatch by suffix** — a caller asks for `boot.cfg`; the file
  found decides the engine.
- **Several search roots**, local or remote, searched in order, plus
  per-caller candidate names and paths (`web01.boot.cfg` before `boot.cfg`).
- **Includes that search the same way** — `{% include %}`, `<%include/>`,
  `{{> partial}}` and the rest resolve through the lookup that loaded the file.
- **One undefined-variable policy** (`strict`, `lenient`, `debug`) that means
  the same thing in every engine that can honour it.
- **Your encoding of the data** — a `DataEncoder` subclass decides what is a
  structure and how values are written and flattened for the engines that
  cannot run Python.
- **Byte-exact fallback** — an unclaimed file is copied as it is, never decoded.
- **Pluggable** — an engine is a class with a suffix list and a priority,
  registered directly or through the `tplx.engines` entry point, and checked by
  the shipped `tplx.testing.EngineContract` suite.
- **Nothing required** — each engine's library is an extra, imported only when a
  file needs it.

## Installation

```bash
pip install tplx
```

| Extra | Adds | Needed for |
| --- | --- | --- |
| `jinja` | `jinja2` | `.j2`, `.jinja`, `.jinja2` |
| `mako` | `mako` | `.mako` |
| `liquid` | `python-liquid` | `.liquid` |
| `handlebars` | `pybars3` | `.hbs`, `.handlebars` |
| `mustache` | `chevron` | `.mustache` |
| `cli` | `duho` | the `tplx` command |

`.erb` needs `ruby` on `PATH` and `.epp` needs `puppet`; neither has an extra.

## Quick start

```python
from tplx import Loader

loader = Loader(["templates"])
text = loader.render("boot.cfg", {"hostname": "web01"}, release="13")
```

A caller with its own search order binds it once; includes follow it:

```python
lookup = loader.lookup(
    candidates=lambda name: [f"web01.{name}", name],
    paths=["debian"],  # templates/debian/ before templates/
)
text = lookup.render("boot.cfg", hostname="web01")
```

## Command line

```bash
pip install "tplx[cli,jinja]"
tplx render templates/boot.cfg.j2 -s hostname=web01      # one file
tplx render boot.cfg -r templates -d host.json -o boot.cfg  # a name, data from JSON
tplx find boot.cfg -r templates                          # which file, which engine
tplx engines                                             # what is registered
```

`-s a.b=v` nests and merges into `--data`; `-s n=json:3` passes JSON. Exit
status: `0` done, `1` the template or an engine failed, `2` a usage error.

## API overview

| Module | Purpose |
| --- | --- |
| `tplx` | `Loader`, `Lookup`, the engines, the `Template` contract and the registry |
| `tplx.exceptions` | `TplxError` and its subclasses |
| `tplx.engines` | the shipped engine classes |
| `tplx.testing` | `EngineContract`, the suite every engine passes |
| `tplx.cli` | the `tplx` command (`cli` extra) |

## Development

```bash
python -m venv .venv/3.14-nt-arm64
.venv/3.14-nt-arm64/Scripts/python -m pip install -e ".[dev,docs]"
.venv/3.14-nt-arm64/Scripts/python -m pytest -q -rs
```

### Releasing

This project follows [Semantic Versioning](https://semver.org/) and keeps a
[`CHANGELOG.md`](https://github.com/jose-pr/tplx/blob/main/CHANGELOG.md).
Pushing a tag matching `v*` triggers the release workflow: test gate → build
(checking the tag names the version built) → a strict docs build as a gate →
GitHub release → publish. The release workflow never deploys the docs site
itself: for a final release its last job dispatches the docs workflow at the
tag, which owns every Pages deploy.

## License

MIT — see [LICENSE](https://github.com/jose-pr/tplx/blob/main/LICENSE).
