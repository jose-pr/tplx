# tplx

Render a tree of templates where **each file's suffix picks its engine and its
stem names what it renders**: `boot.cfg.j2` is Jinja, `boot.cfg.mako` is mako,
and both answer to `boot.cfg`. A file no engine claims is copied byte for byte.

## Installation

```bash
pip install tplx
```

| Engine | Suffixes | Install | Undefined names | Includes |
| --- | --- | --- | --- | --- |
| Jinja | `.j2` `.jinja` `.jinja2` | `tplx[jinja]` | strict, lenient, debug | `{% include %}` `{% extends %}` `{% import %}` `{% from %}` |
| mako | `.mako` | `tplx[mako]` | strict, lenient (`debug` is lenient) | `<%include/>` `<%inherit/>` `<%namespace/>` |
| Liquid | `.liquid` | `tplx[liquid]` | strict, lenient, debug | `{% include %}` `{% render %}` |
| Handlebars | `.hbs` `.handlebars` | `tplx[handlebars]` | always empty | `{{> name}}` |
| Mustache | `.mustache` | `tplx[mustache]` | always empty | `{{> name}}` |
| Go (`text/template`) | `.tmpl` `.gotmpl` | `tplx[go]`, Python 3.11+ | strict; otherwise `<no value>` | `{{template "name" .}}` |
| ERB | `.erb` | `ruby` on `PATH` | Ruby's `nil` | — |
| EPP | `.epp` | `puppet` on `PATH` | Puppet's `undef` | — |
| shell (`%{NAME}`) | `.shtpl` | — | strict, lenient, debug | — |
| envsubst (`$NAME`, GNU, a8m or drone) | `.envsubst` `.template` | — | strict, lenient, debug | — |
| copy | any other | — | n/a: the bytes as stored | — |

Each library-backed engine is an extra of that name; the `cli` extra adds the
[`tplx` command](cli.md).

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

## Trust

Templates and their roots are trusted, in every engine alike: Jinja and
mako run Python, ERB and EPP run Ruby and Puppet. What tplx guards is the
template **name**: one that would leave the search paths (`..`, a backslash,
a drive) is refused.

## Learn more

- [Command line](cli.md)
- [API reference](api/reference.md)
- [Changelog](changelog.md)
