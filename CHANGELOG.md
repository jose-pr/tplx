# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `Loader` and `Lookup`: find a template by name (an exact file name, or the
  lowest-sorting file whose stem is the name) under several roots, with
  per-caller `candidates` and `paths`, and render it with the engine its suffix
  names. `render(name, data, **overrides)`; `name` may be a list of names,
  the first one found wins.
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
- The `tplx` command (`cli` extra): `tplx render`, `tplx find`,
  `tplx engines`.
- `TplxError` and its subclasses in `tplx.exceptions`; the `TPLX_RUBY` and
  `TPLX_PUPPET` environment variables.

[Unreleased]: https://github.com/jose-pr/tplx/commits/main
