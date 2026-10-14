# `tplx` — public API header

Header-file-style reference for the `tplx` package: every public export with
its signature, arguments, contract and gotchas, so the package can be used
without reading its source. It ships inside the package and is
self-contained. Development documentation lives with the source at
<https://github.com/jose-pr/tplx>.

Every public name is importable from `tplx`, except `EngineContract`, which
is in `tplx.testing`; `tplx.exceptions`, `tplx.engines` and `tplx.testing` are
public too. Modules whose name starts with an underscore
are private.

`pip install tplx` gives the loader, the shell engine and the copy engine with
no dependency. The `cli` extra (duho) adds the `tplx` command. Each other
engine's library is an extra: `jinja` (jinja2),
`mako`, `liquid` (python-liquid), `handlebars` (pybars3), `mustache`
(chevron). `.erb` needs `ruby` and `.epp` needs `puppet` on `PATH`.

`tplx.__version__` is the installed distribution's version.

Templates and their roots are trusted, in every engine alike: Jinja and
mako run Python, ERB and EPP run Ruby and Puppet. What tplx guards is the
template **name**: one that would leave the search paths (`..`, a backslash,
a drive) is refused.

## Loading and rendering (`tplx`)

```python
Loader(roots=(), *, engines=None, undefined="strict", globals=None, encoder=None, configure=None)
```

Finds templates under `roots` and renders them with the engine each needs.
Type aliases: `Names = str | Sequence[str]` (one name, or several tried in
order) and `Candidates = Callable[[str], Iterable[str]]`.

- `roots`: directories searched in order. A `str` or `os.PathLike` is a local
  `pathlib.Path`; any object with pathlib's `/`, `exists`, `iterdir`,
  `is_file`, `name`, `stem`, `suffix`, `read_bytes` and `stat` is used as it is (remote paths
  from `pathlib_next` qualify). Empty means `templates` in the working
  directory (`DEFAULT_ROOT`).
- `engines`: the engine classes to consider; default the registry as it is
  now (a snapshot). Always ordered by `PRIORITY`, highest first.
- `undefined`: one of `UNDEFINED_MODES` = `("strict", "lenient", "debug")`;
  anything else raises `ValueError`.
- `globals`: names every render sees, beneath the data passed to `render`.
- `encoder`: the `DataEncoder` that presents the data to the engines that
  cannot evaluate Python; default `DataEncoder()`.
- `configure`: `{EngineClass: function}`; each function is called once with
  that engine's own environment when a lookup builds it, for the class and its
  subclasses (see "Configuring an engine"). Anything but a class mapped to a
  callable raises `TypeError`.
- Attributes: `roots`, `engines` (tuple), `undefined`, `globals` (dict),
  `encoder`, `configure` (dict).

**Resolution**: a name may hold directories (`debian/boot`), separated by
`/`. A name with a `..` segment, a backslash, a NUL or a drive (`C:/x`,
`//host/share`) raises `TemplateNotFound`, on every platform. Wherever a name is taken (`render`, `get`, `find`,
`resolve`), a **list of names** may be given instead: each is tried in turn,
with all of its candidates in every search path, and the first file found
wins (`render(["web01.boot.cfg", "boot.cfg"])`). An empty list is a
`ValueError`. A `str` is always one name. In each directory an exact file
name wins; otherwise, among the files whose **stem** is the name (`boot.cfg`
finds `boot.cfg.j2`), the one whose suffix the highest-`PRIORITY` engine
claims, then the lowest name: `boot.cfg.j2` beats a leftover `boot.cfg.bak`,
which only the copy engine claims. Directories are never matched. The first
engine whose `can_process` accepts the file
builds it, so **the suffix picks the engine**. Files are read as bytes; a text
engine needs UTF-8.

```python
Loader.lookup(*, candidates=None, paths=()) -> Lookup
```

The loader bound to one caller's search. `candidates(file_name) ->
Iterable[str]` lists the file names to try for the **last part** of a name,
most specific first (default: only that file name); the directory part
(`debian/` in `debian/boot`) is kept, and a candidate holding a `/` never
matches. `paths` are searched before the roots: an anchored one (absolute,
rooted, or containing `://`) as it is, a relative one inside each root.
Includes inside a template go through the same lookup. The same arguments
return the same `Lookup` when they are hashable, among the
`LOOKUP_CACHE_SIZE` (64) most recently used: define `candidates` once rather
than a new function per call.

```python
Loader.render(name, data=None, /, *, candidates=None, paths=(), **overrides) -> str | bytes
Loader.get(name, **lookup) -> Template
Loader.find(name, **lookup) -> Source
```

One-shot forms of the `Lookup` methods. A data name that is `candidates` or
`paths` goes in `data`.

```python
Lookup.render(name, data=None, /, **overrides) -> str | bytes
```

The template's top-level names are the loader's `globals`, then `data`, then
`overrides` (later wins). Returns text, or `bytes` from a `BINARY` engine (the
copy engine). Raises everything `get` raises; an engine failure is
`RenderError` with the engine's exception as `__cause__`; a missing name under
`strict` is `UndefinedError`; a missing include is `TemplateNotFound`.

```python
Lookup.get(name) -> Template
```

The compiled template, cached by name while its file is unchanged (a more
specific file added later is found after `clear()`). Raises
`TemplateNotFound`, `NoEngineError` (no engine claims the file, or it is not
UTF-8 for a text engine), `EngineUnavailableError` (the claiming engine's extra
or program is missing), `RenderError` (it does not compile).

```python
Lookup.find(name) -> Source
```

The file for `name`, read. Raises `TemplateNotFound`.

```python
Lookup.resolve(name) -> tuple[Source, type]
```

The file a render of `name` reads and the engine class that renders it,
without compiling anything. Raises `TemplateNotFound`, `NoEngineError`.

```python
Lookup.include(name, engine) -> Include
Lookup.render_include(name, values) -> str
```

What an engine's include hook calls. `include` finds `name` and picks its
engine exactly as `get` would; when that engine is `engine` (the including
one), `Include.text` is the source to compile natively, otherwise `None`.
`render_include` renders `name` with its own engine and `values` (the
including template's current data) and returns the text to insert; bytes that
are not UTF-8 raise `NoEngineError`.

```python
class Include(NamedTuple): source: Source; engine: type; text: str | None
```

- `Lookup.search_paths() -> list`: the directories searched, in order.
- `Lookup.clear()`: forget the compiled templates and engine state.
- `Lookup.state(key, factory)`: per-lookup state an engine builds once (its
  `Environment`, its `TemplateLookup`).
- Attributes: `loader`, `candidates`, `paths`.

```python
class Source(NamedTuple): data: bytes; name: str; origin: str; uptodate: Callable[[], bool]
```

A file as found: its bytes, the file name found, its path or URI as text, and
a check that is true while it is unchanged.

## Presenting data (`tplx`)

Jinja and mako receive the data as it is. The other engines receive it
through the loader's `DataEncoder`, which a subclass changes the way a
`json.JSONEncoder` subclass does.

```python
DataEncoder(*, expose=(), max_depth=8)
```

- `view(values) -> dict` — for Liquid, Handlebars, Mustache: a structure
  becomes a `DataView` (a lazy, read-only `Mapping` of its items or
  attributes; dunder names hidden), a list stays a list, a value as it is.
- `json(values)` — for ERB, EPP: a JSON-serialisable copy; a value that is not
  a JSON scalar (a NaN or an infinity included) is written as its `str()`.
- `flatten(values) -> dict[str, str]` — for the shell engine: one level,
  keyed by `key(path)`, each value through `text(value)`. List items are
  keyed by index. Two paths giving one key log a warning; the later wins.
- `json` and `flatten` drop `_`-prefixed names unless `expose` lists them
  (`view` keeps them), name a key that is not a `str` by its text (`10` is
  `"10"`), stop at `max_depth` (a structure that deep is written as its
  text), and skip a reference back to an object already on the path.

The hooks to override:

- **`default(value)`** — what a value that is not in `SCALARS`, a mapping, a
  list or a tuple stands for: return a `Mapping` to make it a structure,
  anything else to make it that value. Default: an object whose class defines
  its own `__str__` is a value (an address, a MAC, a path is written as its
  text); any other object with attributes is a structure of its attributes.
- **`key(path) -> str`** — the flattened name of the value at `path` (a
  sequence of names); default `"_".join(path).upper()`.
- **`text(value) -> str`** — how `flatten` writes a value; default `None` is
  `""`, a boolean `true`/`false`, anything else `str()`.
- **`SCALARS`** — the class attribute listing types that are always values:
  `str`, `bytes`, `bool`, `int`, `float`, `complex`, `None`, the `ipaddress`
  addresses and networks, `os.PathLike`.

Also: `structure(value)` (a value as a `Mapping`, a `list` or a value) and
`wrap(value)` (one value as `view` presents it).

## Includes

An engine's own include syntax goes back through the `Lookup` that loaded
the including file, so an include finds **the same file and the same engine a
render of that name would**: same roots, candidates and paths, same stem
rule. Names are root-relative, never relative to the including file.

- A file the including engine claims is compiled by it, so blocks, macros,
  `extends` and the including template's context all work as the engine
  documents.
- Any other file is rendered by its own engine with the including template's
  current data (Jinja: the whole context, loop variables included; mako: the
  render's arguments; Liquid, Handlebars, Mustache: the render's data) and its
  output is inserted as text, never parsed by the including engine. A file the
  copy engine claims is inserted as it is.

| Engine | Syntax |
| --- | --- |
| Jinja | `{% include %}`, `{% extends %}`, `{% import %}`, `{% from %}` |
| mako | `<%include file=.../>`, `<%inherit file=.../>`, `<%namespace file=.../>` |
| Liquid | `{% include %}`, `{% render %}` |
| Handlebars, Mustache | `{{> name}}` |
| shell, ERB, EPP, copy | none |

## Engines (`tplx`, `tplx.engines`)

| Class | Suffixes | Extra / program | Undefined modes |
| --- | --- | --- | --- |
| `JinjaTemplate` | `.j2 .jinja .jinja2` | `jinja` | all three |
| `MakoTemplate` | `.mako` | `mako` | strict; `debug` is `lenient` |
| `LiquidTemplate` | `.liquid` | `liquid` | all three |
| `HandlebarsTemplate` | `.hbs .handlebars` | `handlebars` | always empty |
| `MustacheTemplate` | `.mustache` | `mustache` | always empty |
| `ERBTemplate` | `.erb` | `ruby` (`TPLX_RUBY`) | none: Ruby `nil` |
| `EPPTemplate` | `.epp` | `puppet` (`TPLX_PUPPET`) | none: Puppet `undef` |
| `ShellTemplate` | `.shtpl` | — | all three |
| `EnvsubstTemplate` | `.envsubst .template` | — | all three |
| `CopyTemplate` | any, `FALLBACK_PRIORITY` | — | n/a, returns `bytes` |

- **Jinja** keeps a template's trailing newline and, as Jinja does by
  default, writes every line ending as `\n`: a CRLF template renders LF.
- **mako** drops a data name it reserves (`RESERVED_NAMES`: `self`,
  `context`, `next`, ...) with a warning.
- **Liquid, Handlebars, Mustache** read the data through
  `DataEncoder.view`: structures as read-only mappings, lists as lists.
- **Every engine keeps its own defaults**; tplx does not change them. In
  particular **Handlebars and Mustache HTML-escape `{{x}}`** (`&` is written
  `&amp;`), as their specifications say: write `{{{x}}}` (Mustache also
  `{{& x}}`) for the value as it is, which is what a config file usually
  wants. Jinja (no autoescape), mako, Liquid, ERB, EPP and the shell engine
  write values unescaped.
- **Handlebars, Mustache** cannot fail on an undefined name. Another
  engine's output included in a Mustache template must not contain the bytes
  `\x01` or `\x02`, which delimit it. A partial that cannot be found raises
  `TemplateNotFound` under `strict` and renders empty otherwise. Partials are
  compiled once per lookup and reused while their file is unchanged.
  Handlebars can drop the `\r` of a CRLF that follows a tag: keep its
  templates LF.
- **ERB, EPP** receive the data as JSON from `DataEncoder.json`, so
  `_`-prefixed names are dropped unless the encoder's `expose` lists them. ERB: `@context` is the whole hash and
  each other top-level name is also `@name` (a name `context` stays
  `@context['context']`). EPP: each top-level name is a
  parameter. Output is the template's own bytes; EPP output has CRLF turned
  into LF. `SubprocessTemplate.TIMEOUT` (60 s) bounds a render: the program
  runs in its own process group, and a timeout kills it and its children (a
  `puppet.bat` shim included). Output that is not UTF-8 is decoded with
  replacement characters. ERB needs Ruby 2.6 or later (ERB's `trim_mode:`
  keyword); tested with Ruby 4.0 and Puppet 8.10.
- **Shell**: `%{NAME}` from `DataEncoder.flatten`, matched
  case-insensitively; by default `target.hostname` is `%{TARGET_HOSTNAME}`,
  list items are numbered, `None` renders empty, booleans `true`/`false`, and
  an unexposed `_`-prefixed name is absent; `%{NAME:-default}` and
  `%{NAME-default}` as in POSIX shells, `%{NAME:1:3}` and `%{NAME: -2}` slices
  and `%{NAME/pattern/text}` (`//` all, `/#` start, `/%` end; the pattern a
  bash glob) as in bash; `%%` is `%`. A bare `%word` is text, and so is an
  expression the engine does not know (`%{NAME:?x}`): its `%` is written and
  the scan goes on inside it. Subclass to change `EXT`, `DELIMITER`,
  `PATTERN` (`braced`, `unbraced`, `all`) or `FEATURES`, a subset of
  `ShellTemplate.ALL_FEATURES`: `escape`, `default`, `assign` (`=`, `:=`), `alternate` (`+`,
  `:+`), `nested` (a default is substituted), `unquote`, `slice`, `replace`,
  `trim` (`#`, `##`, `%`, `%%`), `case` (`^`, `^^`, `,`, `,,`), `length`
  (`{#NAME}`). The shell engine has `escape default unquote slice replace`.
- **envsubst**: `$NAME` and `${NAME}`, from the data like the shell engine
  (names match case-insensitively; `tplx render --env` passes the
  environment). `DIALECT` (subclass to change it) is one of
  `EnvsubstTemplate.DIALECTS`:
  `gnu`, the default, as GNU envsubst: no defaults, no `$$` escape, anything
  else left as text; `a8m` as github.com/a8m/envsubst: defaults, `=`, `+`
  and nested words, `$$` escapes; `drone` as github.com/drone/envsubst:
  braced only, defaults, slices, replacements, trims, case and length, `$$`
  escapes. Setting `PATTERN` or `FEATURES` in a subclass overrides the
  dialect's (`FEATURES = frozenset({"default"})` for GNU plus `${A:-x}`).
  Departures, each on purpose: names are case-insensitive; a slice or
  replacement follows bash where drone does not (negative offsets, glob
  patterns); an expression a dialect lacks is text, never an error. An
  undefined name follows the undefined mode: `-u debug` keeps the
  `$request_uri` of an nginx template, as the nginx image's envsubst does.
- **Copy**: the file's bytes, never decoded; on its first render, warns when
  the file is UTF-8 text that still holds a `%{NAME}` placeholder.

An optional engine is registered whether or not its library is installed, and
`import tplx` imports none of them.

### Configuring an engine

`Loader(configure={EngineClass: function})` hands each engine's own
environment to `function` once per lookup, before any template is compiled,
so filters, helpers and options reach every template and include:

| Engine | `function` receives | For example |
| --- | --- | --- |
| `JinjaTemplate` | `jinja2.Environment` | `env.filters["quote"] = shlex.quote` |
| `LiquidTemplate` | `liquid.Environment` | `env.filters["quote"] = shlex.quote` |
| `MakoTemplate` | `mako.lookup.TemplateLookup` | `lookup.template_args["imports"] = ["from shlex import quote"]` |
| `HandlebarsTemplate` | the `dict` of helpers every render passes | `helpers["quote"] = lambda this, v: shlex.quote(v)` |

Mustache, the shell engine, ERB, EPP and copy have no environment; an entry
for them is never called. A key matches its subclasses, and several matching
keys run in the order given. `Template.configure_native(native)` is what an
engine (a plugin's too) calls to apply them.

## The engine contract (`tplx`)

```python
class Template:
    EXT: None | str | tuple[str, ...] = ()   # () none, None or "*" every suffix
    PRIORITY: int = DEFAULT_PRIORITY         # 0; FALLBACK_PRIORITY is -100
    BINARY: bool = False                     # True: receive and return bytes
    def __init__(self, source, *, lookup=None, origin="<string>"): ...
    def render(self, data=None, /, **overrides) -> str | bytes: ...
    def render_values(self, values: Mapping) -> str | bytes: ...  # implement this
    @classmethod
    def can_process(cls, file, source) -> bool: ...
```

- An engine implements `render_values`; `render` merges `data` and
  `overrides`, calls it, and raises an engine's own exception as `RenderError`
  (its `__cause__`). A template built without a `lookup` renders `strict` and
  has no includes.
- Attributes: `source`, `lookup`, `origin`, `undefined` (the mode),
  `is_up_to_date`.
- `can_process` defaults to `can_process_suffix(cls, file)`: is `file`'s
  suffix (a path or a file name) in `template_extensions(cls)`?
- `template_extensions(cls) -> tuple[str, ...] | None`: `EXT` normalised to
  lowercase dotted suffixes, `None` for every suffix.
- `SubprocessTemplate` is the base for a program-backed engine: set `COMMAND`,
  `ENV_VAR`, `EXT`, implement `command(program, template_path, values_path)`;
  `TIMEOUT`, `NEWLINES` (`"lf"` or `None`), `VALUES_NAME`, `SENTINEL`.

## Registry (`tplx`)

- **`register_engine(cls=None, *, priority=None)`** — add an engine and return
  it; bare or as a decorator. `priority` sets `PRIORITY`. Registering a class
  twice adds it once (a new `priority` still applies); a class that would
  claim a suffix another registered engine claims at the same priority raises
  `ValueError` and changes nothing, the class's `PRIORITY` included.
- **`unregister_engine(cls) -> bool`** — True if it was registered.
- **`registered_engines() -> tuple`** — highest `PRIORITY` first.
- **`by_priority(engines) -> tuple`** — a stable sort by `PRIORITY`.
- **`ENTRY_POINT_GROUP = "tplx.engines"`** — an installed package registers an
  engine class under it; the group is read once, on first use of the
  registry (a concurrent first use waits for it). One that fails to load is
  logged and skipped.
- `DEFAULT_PRIORITY = 0`, `FALLBACK_PRIORITY = -100`, `ANY_SUFFIX = "*"`.

## Testing an engine (`tplx.testing`)

```python
class EngineContract:
    engine: type; source: str | bytes; expected: str | bytes; filename: str | None = None
```

Subclass it in a pytest module: `source` writes the value of `name`, and
`expected` is what it renders with `name="tplx"`. pytest collects the checks
(claims its file, renders through a loader and without one, a keyword wins over
data, bytes exactly when `BINARY`, knows its origin, outranks the fallback).

## Exceptions

All in `tplx.exceptions`, all re-exported from `tplx`.

- `TplxError` — base of every error tplx raises.
- `TemplateNotFound(TplxError, LookupError)` — `.names` (every name tried,
  in order) and `.name` (the first); no file, or a name escapes the search
  paths.
- `NoEngineError(TplxError)` — no engine claims the file, or it is not UTF-8
  for a text engine.
- `EngineUnavailableError(TplxError)` — the engine's extra (`pip install
  tplx[mako]`) or program is missing.
- `RenderError(TplxError)` — an engine failed to compile or render; `__cause__`
  is its own exception.
- `UndefinedError(RenderError, NameError)` — a missing name under `strict`.
- `RenderTimeoutError(RenderError, TimeoutError)` — a program-backed engine
  ran past its timeout.

## Command line

`tplx` (also `python -m tplx`) needs the `cli` extra; without it the command
exits naming the extra. `import tplx` never imports `tplx.cli`.

```text
tplx [--version]
tplx render NAME... [-r ROOT]... [-p PATH]... [-u MODE] [--env] [-d FILE|-] [-s KEY=VALUE]... [-o FILE|-]
tplx find NAME... [-r ROOT]... [-p PATH]... [--json]     (alias: which)
tplx engines [--json]
```

- `NAME` is looked up in the roots; several names are tried in order and
  the first found wins. With no `-r`, a single `NAME` that is an existing
  file is that file, its directory the root.
- `-r/--root` (repeat; default `templates`), `-p/--path` (repeat; searched
  first, relative ones inside each root), `-u/--undefined` (`strict`,
  `lenient`, `debug`).
- `render`: `--env` starts the data from the environment variables;
  `-d/--data` a JSON object file or `-` for standard input over it;
  `-s/--set key=value` over it (repeat; `a.b=v` nests and merges into
  `--data`; a value `json:...` is JSON); `-o/--output` a file or `-`. Output
  is written as bytes, unchanged.
- `find` prints `<origin>\t<Engine>`, or `{"origin", "engine"}` with `--json`.
- `engines` prints `<Engine>\t<suffixes>\t<priority>` per engine, highest
  priority first, or a JSON array with `--json`.
- `render` and `find` also take `-v`/`-q` and `--loglevel [NAME:]LEVEL`.
- Exit status: `0` done, `1` the operation failed (no such template, an
  engine error, a file that cannot be read or written), `2` a usage error. A
  failure prints `tplx: error: <message>` on standard error.

## Environment variables

- `TPLX_RUBY` — the `ruby` the ERB engine runs; default: `ruby` on `PATH`.
- `TPLX_PUPPET` — the `puppet` the EPP engine runs; default: `puppet` on
  `PATH`.

## Gotchas

- Building an engine class directly (`JinjaTemplate("{% if %}")`) raises the
  engine library's own compile error; `Lookup.get` raises it as
  `RenderError`. Rendering raises `RenderError` either way.
- A `str` root is always local: pass a path object for a URI.
- A compiled template is reused while **its own** file is unchanged; adding a
  file that would now win (an earlier candidate, an exact name) takes effect
  after `Lookup.clear()` or with a new `Loader`.
- The logger is `tplx`; nothing is configured on import.
