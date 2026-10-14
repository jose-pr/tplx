# tplx

Render a tree of templates where **each file's suffix picks its engine and its
stem names what it renders**: `boot.cfg.j2` is Jinja, `boot.cfg.mako` is mako,
and both answer to `boot.cfg`. A file no engine claims is copied byte for byte.

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

## 30-second tour

```python
from tplx import Loader

loader = Loader(["templates"])
text = loader.render("boot.cfg", {"hostname": "web01"}, release="13")
```

`boot.cfg` finds `templates/boot.cfg.j2` (or `.mako`, `.liquid`, `.shtpl`,
...), and the suffix decides which engine renders it. Includes inside it search
the same roots.

## Each engine keeps its defaults

tplx picks the engine; it does not change how that engine behaves. Write a
template the way its engine's own documentation says. The difference most
likely to surprise in a generated file is escaping:

| Engine | A plain value tag writes | For the value as it is |
| --- | --- | --- |
| Handlebars | HTML-escaped (`&` is `&amp;`) | `{{{x}}}` |
| Mustache | HTML-escaped | `{{{x}}}` or `{{& x}}` |
| Jinja, mako, Liquid, ERB, EPP, shell | the value as it is | — |

## Learn more

- [API reference](api/reference.md)
- [Changelog](changelog.md)
