# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-15

### Added

- `Loader` and `Lookup`: find a template by name (an exact file name, or the
  file whose stem is the name and whose suffix the highest-priority engine
  claims, so `boot.cfg.j2` beats a leftover `boot.cfg.bak`) under several
  roots, with
  per-caller `candidates` and `paths`, and render it with the engine its suffix
  names. `render(name, data, **overrides)`; `name` may be a list of names,
  the first one found wins. A name holding `..`, a backslash or a drive is
  refused on every platform. `Lookup.clear()`; `LOOKUP_CACHE_SIZE`.
- Engines: Jinja, mako, Liquid, Handlebars, Mustache (each behind an extra of
  that name), ERB (`ruby`), EPP (`puppet`), a `%{NAME}` shell engine and a
  byte-exact copy engine for every other file.
- Includes in Jinja, mako, Liquid, Handlebars and Mustache resolve through the
  lookup that loaded the including file, to the same file and engine a render
  of that name would use: a file of another engine is rendered by that engine
  with the current data and its output inserted.
- `undefined="strict" | "lenient" | "debug"` for every engine that can honour
  it.
- The engine registry (`register_engine`, `unregister_engine`,
  `registered_engines`, the `tplx.engines` entry-point group) and
  `tplx.testing.EngineContract`, the suite every engine passes.
- `DataEncoder`, the loader's `encoder=`: how data reaches Liquid,
  Handlebars, Mustache (`view`), ERB and EPP (`json`) and the shell engine
  (`flatten`); a subclass overrides `default`, `key` and `text`.
- `Loader(configure={EngineClass: function})`: Jinja and Liquid environments,
  the mako `TemplateLookup` and the Handlebars helpers, set up once per lookup.
- The `tplx` command (`cli` extra): `tplx render`, `tplx find`,
  `tplx engines`.
- `TplxError` and its subclasses in `tplx.exceptions`; the `TPLX_RUBY` and
  `TPLX_PUPPET` environment variables.

[Unreleased]: https://github.com/jose-pr/tplx/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jose-pr/tplx/releases/tag/v0.1.0
