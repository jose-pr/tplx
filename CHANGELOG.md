# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `Template.is_template(text)`: does a text hold the engine's syntax, without
  compiling it; every built-in engine finds only its own.
- `DollarTemplate`: the shell syntax with `$` (`${HOST:-localhost}`),
  registered for no suffix; the new `tplx.DEFAULT_ENGINE`.

### Fixed

- `tplx.evaluate` and `Loader.evaluate` took a bare expression where a
  template engine takes a template. They are now `tplx.eval` and
  `Loader.eval`, and the engine decides (`Template.eval`): `"{{ port + 1 }}"`
  is `81`, `"Test {{ port }}"` is `"Test 80"`, and text with no syntax comes
  back as it is, compiled never.
- The default engine was Python's `eval`, which ran code and no template;
  `tplx.DEFAULT_ENGINE` is now `DollarTemplate`, and `"python"` and
  `tplx.PYTHON` are gone.
- An engine's `Template.evaluate(expression)` is gone: `Template.eval(text)`
  takes the whole text, and a plugin engine that gave typed values overrides
  `_evaluate_expression`.

- A sandboxed template or expression could make the process allocate without
  bound (`"x" * 10**10`, `[0] * 50000000`, `"x".center(n)`, a format width,
  Go's `printf` width): `SandboxLimits.max_output` now bounds every value a
  sandboxed template builds, refused before it is allocated, and every value
  `eval` returns.

## [0.1.5] - 2026-10-15

### Added

- `SandboxLimits(max_output, max_iterations, max_depth)`: what one sandboxed
  render may cost, `Loader(sandbox=SandboxLimits(...))`; `sandbox=True` uses
  the defaults (1,000,000 characters, 100,000 iterations, depth 100). Going
  over raises `SandboxError`.

### Fixed

- Presenting data to Liquid, Mustache, Handlebars and any sandboxed engine
  converted a list every time it was reached: a shared list (YAML aliases)
  cost time exponential in its nesting, and a list containing itself exceeded
  the recursion limit. Each distinct list is now converted once.

### Changed

- In a sandbox only a function the caller passes stays callable; a class or a
  callable object reaches the template as data it cannot call.
- The `jinja`, `liquid` and `mako` extras require jinja2 3.1.6, python-liquid
  2.2.1 and mako 1.3.12: every earlier release has a published security
  advisory (two Jinja sandbox escapes among them).

## [0.1.4] - 2026-10-15

### Added

- `Loader(sandbox=True)` for untrusted templates: only engines with
  `SANDBOXED = True` take part (Jinja through `SandboxedEnvironment`, Liquid,
  Mustache, Handlebars, Go through a gotpl `SandboxPolicy`, shell, envsubst,
  copy); a file another engine claims raises `SandboxError` before it is read.
  A sandboxed template sees plain data: no method of the caller's objects, and
  a value that is not a plain type as its text.
- `tplx.evaluate` and `Loader.evaluate`: an expression's value, its type kept,
  in Python (`DEFAULT_ENGINE`, refused by a sandbox) or an engine's syntax
  (`engine="jinja"`, `".liquid"`, `"go"`, ...), through `Template.evaluate`.
- `Loader.compile`, cached; `Template.references()`, the names a template
  reads.

## [0.1.3] - 2026-10-15

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

[Unreleased]: https://github.com/jose-pr/tplx/compare/v0.1.5...HEAD
[0.1.5]: https://github.com/jose-pr/tplx/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/jose-pr/tplx/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/jose-pr/tplx/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/jose-pr/tplx/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/jose-pr/tplx/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/jose-pr/tplx/releases/tag/v0.1.0
