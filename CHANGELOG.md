# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `CheetahTemplate` (`.cheetah`): Cheetah, Cobbler's kickstart language,
  rendered by CT3 behind the `cheetah` extra. `#include` resolves through the
  lookup; all three undefined modes apply; `configure` sets Cheetah's
  compiler settings.

### Changed

- A `.cheetah` file is rendered by the Cheetah engine; 0.1.2 copied it byte
  for byte.

## [0.1.2] - 2026-10-15

### Added

- `GoTemplate` (`.tmpl`, `.gotmpl`): Go's `text/template`, rendered by the
  pure-Python gotpl, behind the `go` extra (Python 3.11 or later).
  `{{template}}` names resolve through the lookup; Sprig and other functions
  come through `Loader(configure={GoTemplate: ...})`.

### Changed

- A `.tmpl` or `.gotmpl` file is rendered by the Go engine; 0.1.1 copied it
  byte for byte.

## [0.1.1] - 2026-10-15

### Added

- `EnvsubstTemplate` (`.envsubst`, `.template`): `$NAME` and `${NAME}` as
  envsubst writes them. `DIALECT` is `gnu` (the default: no defaults, no `$$`
  escape), `a8m` or `drone`; `PATTERN` and `FEATURES` override a dialect's.
- The shell engine slices (`%{NAME:1:3}`, `%{NAME: -2}`) and replaces
  (`%{NAME/pattern/text}`, `//`, `/#`, `/%`) as bash does; `FEATURES` turns
  each piece of syntax on or off.
- `tplx render --env` starts the data from the environment variables.

### Changed

- A `.envsubst` or `.template` file is rendered by the envsubst engine; 0.1.0
  copied it byte for byte.
- The shell engine leaves an expression it does not know as text and goes on
  scanning inside it, so a placeholder there is still substituted.

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

[Unreleased]: https://github.com/jose-pr/tplx/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/jose-pr/tplx/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/jose-pr/tplx/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/jose-pr/tplx/releases/tag/v0.1.0
