"""Finding a template by name and handing it to the engine that claims it."""

from __future__ import annotations

import builtins
import os
import pathlib
import sys
from collections import OrderedDict
from pathlib import PurePosixPath, PureWindowsPath
from typing import (
    Any,
    Callable,
    Dict,
    Hashable,
    Iterable,
    List,
    Mapping,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from . import _registry
from . import _template
from ._registry import FALLBACK_PRIORITY, by_priority, template_extensions
from ._encoder import DataEncoder, unwrap
from ._template import UNDEFINED_MODES, Template, can_process_suffix
from .exceptions import (
    NoEngineError,
    RenderError,
    SandboxError,
    TemplateNotFound,
    TplxError,
    UndefinedError,
)

#: Where templates are looked for when a `Loader` is given no root.
DEFAULT_ROOT = "templates"

#: `candidates(name)` returns the file names to try for `name`, in order.
Candidates = Callable[[str], Iterable[str]]

#: One template name, or several tried in order (the first found wins).
Names = Union[str, Sequence[str]]

#: How many `Lookup`s a `Loader` keeps for reuse; the least recently used goes.
LOOKUP_CACHE_SIZE = 64

#: How many string templates a `Lookup` keeps compiled, by engine and source.
STRING_CACHE_SIZE = 256

#: The built-in expression engine's name: Python's own `eval`. It is trusted,
#: like every engine, and a sandbox refuses it.
PYTHON = "python"

#: An engine class, or an engine's name or suffix (`"jinja"`, `".j2"`, `"go"`),
#: or `PYTHON`.
EngineChoice = Union[type, str]


def _escapes(name: str) -> bool:
    """Could `name` reach outside a search path on some platform?

    A `..` segment, a backslash (a separator on Windows), a NUL, or a drive or
    UNC share (`C:/x`, `//host/share`) is refused everywhere, so a name means
    the same file on every platform.
    """
    if "\\" in name or "\x00" in name or PureWindowsPath(name).drive:
        return True
    return ".." in PurePosixPath(name.lstrip("/")).parts


def _names(name: "Names") -> List[str]:
    """`name` as a list of names, each refused when it escapes the search paths."""
    names = [name] if isinstance(name, str) else list(name)
    if not names:
        raise ValueError("no template name given")
    for each in names:
        if not isinstance(each, str):
            raise TypeError(f"a template name is a str, not {type(each).__name__}")
        if _escapes(each):
            raise TemplateNotFound(
                each, f"template name escapes the search paths: {each!r}"
            )
    return names


def _key(name: "Names") -> Hashable:
    return name if isinstance(name, str) else tuple(name)


class Source(NamedTuple):
    """A template file as found: its bytes, where it came from, and a freshness check."""

    data: bytes
    #: The file name found, which may be a stem match for the name asked for.
    name: str
    #: The file's path or URI, for messages.
    origin: str
    #: True while the file is unchanged since it was read.
    uptodate: Callable[[], bool]


class Include(NamedTuple):
    """An include as `Lookup.include` resolved it."""

    source: Source
    #: The engine that renders the file, chosen exactly as for a render.
    engine: type
    #: The source text when that engine is the including one, which then
    #: compiles it itself; `None` when the file is rendered by `engine` and its
    #: output inserted.
    text: Optional[str]


def _as_path(value):
    """A root or search path as a path object; a `str` is a local path."""
    if isinstance(value, (str, os.PathLike)) and not hasattr(value, "iterdir"):
        return pathlib.Path(value)
    return value


def _is_anchored(path) -> bool:
    """Does `path` name its own location, so no root applies to it?

    A URI is anchored by its scheme; a local path by a drive or a leading
    separator (`/srv/tftp` is not `is_absolute()` on Windows, but it is rooted).
    """
    text = str(path)
    if "://" in text or text.startswith(("/", "\\")):
        return True
    try:
        return bool(path.is_absolute())
    except (AttributeError, NotImplementedError):  # pragma: no cover
        return False


def _origin(path) -> str:
    try:
        return os.fspath(path)
    except (TypeError, NotImplementedError):
        return str(path)


def _claimed_priority(entry, engines: "Sequence[type]") -> int:
    """The `PRIORITY` of the first engine whose suffixes claim `entry`."""
    for cls in engines:
        if can_process_suffix(cls, entry):
            return int(cls.PRIORITY)
    return FALLBACK_PRIORITY - 1


def _default_engine() -> EngineChoice:
    """`tplx.DEFAULT_ENGINE`, read when it is needed so a caller can set it."""
    package = sys.modules.get(__package__ or "tplx")
    return getattr(package, "DEFAULT_ENGINE", PYTHON)


def _engine_named(engine: EngineChoice, engines: "Sequence[type]") -> EngineChoice:
    """The engine class (or `PYTHON`) that `engine` names among `engines`.

    :raises ValueError: no engine has that name or suffix.
    """
    if isinstance(engine, type):
        return engine
    if not isinstance(engine, str):
        raise TypeError(f"an engine is a class or a name, not {engine!r}")
    word = engine.lower().lstrip(".")
    if word == PYTHON:
        return PYTHON
    known = [PYTHON]
    for cls in engines:
        name = cls.__name__.lower()
        if name.endswith("template") and name != "template":
            name = name[: -len("template")]
        names = [
            name,
            *(suffix.lstrip(".") for suffix in template_extensions(cls) or ()),
        ]
        if word in names:
            return cls
        known.append(name)
    raise ValueError(f"no engine is named {engine!r}; known: {', '.join(known)}")


def _python_evaluate(expression: str, values: "Mapping[str, Any]") -> Any:
    """`expression` through Python's `eval`, with `values` as its names."""
    # The values are globals, not locals, so a comprehension sees them on every
    # Python version (locals are invisible inside one before 3.12).
    namespace: Dict[str, Any] = {str(key): value for key, value in values.items()}
    namespace["__builtins__"] = builtins
    try:
        return eval(expression, namespace)  # noqa: S307 - trusted, refused by a sandbox
    except NameError as exc:
        raise UndefinedError(f"{expression!r}: {exc}") from exc


class _NoFiles:
    """A root with nothing in it: `tplx.evaluate`'s loader reads no file."""

    name = stem = suffix = ""

    def exists(self) -> bool:
        return False

    def __truediv__(self, other: Any) -> "_NoFiles":
        return self

    def __str__(self) -> str:
        return "<no files>"


class _Listing:
    """One directory's entries, indexed by file name and by stem."""

    def __init__(self, entries: "Iterable[Any]") -> None:
        self.by_name: Dict[str, Any] = {}
        self.by_stem: Dict[str, List[Any]] = {}
        for entry in entries:
            self.by_name[entry.name] = entry
            self.by_stem.setdefault(entry.stem, []).append(entry)

    @classmethod
    def of(cls, directory) -> "Optional[_Listing]":
        """`directory`'s listing, or None when it is not a directory."""
        if not directory.exists():
            return None
        try:
            return cls(directory.iterdir())
        except NotADirectoryError:
            return None

    def match(self, filename: str, engines: "Sequence[type]") -> Any:
        """The file for `filename`: the exact name, else the best stem match.

        Among stem matches, the one whose suffix the highest-priority engine
        claims wins, then the lowest name; a leftover such as `boot.cfg.bak`,
        which only the catch-all claims, loses to `boot.cfg.j2`. Directories
        are skipped.
        """
        exact = self.by_name.get(filename)
        if exact is not None and exact.is_file():
            return exact
        ranked = sorted(
            self.by_stem.get(filename, ()),
            key=lambda entry: (-_claimed_priority(entry, engines), entry.name),
        )
        for entry in ranked:
            if entry.is_file():
                return entry
        return None


class Loader:
    """Finds templates under `roots` and renders them with the engine each one needs.

    A name is resolved against every root in order. In each directory an
    exact file name wins; otherwise, among the files whose stem is the name
    (`boot.cfg` finds `boot.cfg.j2`), the one whose suffix the highest-priority
    engine claims, then the lowest name. The engines are consulted highest
    `PRIORITY` first and the first whose `can_process` accepts the file builds
    it, so the suffix picks the engine.

    `engines` defaults to the registry as it is when the loader is built.
    `undefined` is one of `UNDEFINED_MODES`. `globals` are names every render
    sees, under the data passed to `render`. `encoder` presents the data to
    the engines that cannot evaluate Python (a `DataEncoder` by default).
    `configure` maps an engine class to a function called once with that
    engine's own environment whenever a lookup builds one, for the class and
    its subclasses: `{JinjaTemplate: lambda env: env.filters.update(q=quote)}`.
    `sandbox=True` renders untrusted templates: only engines whose class sets
    `SANDBOXED` take part, and a file another engine claims raises
    `SandboxError` before it is read.
    """

    def __init__(
        self,
        roots: "Iterable[Any]" = (),
        *,
        engines: "Optional[Iterable[type]]" = None,
        undefined: str = "strict",
        globals: "Optional[Mapping[str, Any]]" = None,
        encoder: "Optional[DataEncoder]" = None,
        configure: "Optional[Mapping[type, Callable[[Any], Any]]]" = None,
        sandbox: bool = False,
    ) -> None:
        if undefined not in UNDEFINED_MODES:
            raise ValueError(
                f"undefined must be one of {', '.join(UNDEFINED_MODES)}, "
                f"not {undefined!r}"
            )
        self.roots: list = [_as_path(root) for root in roots]
        self.engines: tuple = by_priority(
            _registry.registered_engines() if engines is None else engines
        )
        self.undefined = undefined
        self.globals: dict = dict(globals or {})
        self.encoder = encoder if encoder is not None else DataEncoder()
        self.configure: "Dict[type, Callable[[Any], Any]]" = dict(configure or {})
        for cls, function in self.configure.items():
            if not isinstance(cls, type) or not callable(function):
                raise TypeError(
                    "configure maps an engine class to a callable, "
                    f"not {cls!r} to {function!r}"
                )
        self.sandbox = bool(sandbox)
        self._lookups: "OrderedDict[Hashable, Lookup]" = OrderedDict()

    def lookup(
        self,
        *,
        candidates: "Optional[Candidates]" = None,
        paths: "Sequence[Any]" = (),
    ) -> "Lookup":
        """The loader bound to one caller's file names and search paths.

        `candidates(file_name)` lists the file names to try for the last part
        of a name, most specific first; by default only that file name. The
        directory part of the name is kept. `paths` are searched before the
        roots: an anchored path as it is, a relative one inside each root.
        Includes inside a template resolve through the same `Lookup`. The same
        arguments return the same `Lookup`, which caches what it compiles,
        while it is among the `LOOKUP_CACHE_SIZE` most recently used; pass a
        `candidates` function that is defined once, not a new one per call.
        """
        try:
            key: Hashable = (candidates, tuple(_origin(p) for p in paths))
            hash(key)
        except TypeError:
            return Lookup(self, candidates=candidates, paths=paths)
        found = self._lookups.get(key)
        if found is not None:
            self._lookups.move_to_end(key)
            return found
        found = self._lookups[key] = Lookup(self, candidates=candidates, paths=paths)
        if len(self._lookups) > LOOKUP_CACHE_SIZE:
            self._lookups.popitem(last=False)
        return found

    def find(self, name: "Names", **lookup: Any) -> Source:
        """`self.lookup(**lookup).find(name)`."""
        return self.lookup(**lookup).find(name)

    def get(self, name: "Names", **lookup: Any) -> Template:
        """`self.lookup(**lookup).get(name)`."""
        return self.lookup(**lookup).get(name)

    def render(
        self,
        name: "Names",
        data: "Optional[Mapping[str, Any]]" = None,
        /,
        *,
        candidates: "Optional[Candidates]" = None,
        paths: "Sequence[Any]" = (),
        **overrides: Any,
    ) -> "Union[str, bytes]":
        """`self.lookup(candidates=..., paths=...).render(name, data, **overrides)`.

        A data name that is `candidates` or `paths` goes in `data`.
        """
        return self.lookup(candidates=candidates, paths=paths).render(
            name, data, **overrides
        )

    def evaluate(
        self,
        expression: str,
        context: "Optional[Mapping[str, Any]]" = None,
        /,
        *,
        engine: "Optional[EngineChoice]" = None,
        **overrides: Any,
    ) -> Any:
        """`self.lookup().evaluate(expression, context, engine=engine, **overrides)`."""
        return self.lookup().evaluate(expression, context, engine=engine, **overrides)

    def compile(
        self,
        source: "Union[str, bytes]",
        *,
        engine: "Optional[EngineChoice]" = None,
        name: str = "<string>",
    ) -> Template:
        """`self.lookup().compile(source, engine=engine, name=name)`."""
        return self.lookup().compile(source, engine=engine, name=name)


class Lookup:
    """A `Loader` bound to one set of candidates and search paths.

    Build one with `Loader.lookup`. It caches compiled templates by name, and
    reuses one while its file is unchanged.
    """

    def __init__(
        self,
        loader: Loader,
        *,
        candidates: "Optional[Candidates]" = None,
        paths: "Sequence[Any]" = (),
    ) -> None:
        self.loader = loader
        self.candidates = candidates
        self.paths = tuple(_as_path(path) for path in paths)
        self._templates: Dict[Hashable, Template] = {}
        self._strings: "OrderedDict[Hashable, Template]" = OrderedDict()
        self._state: Dict[Hashable, Any] = {}

    def search_paths(self) -> list:
        """The directories searched, in order: `paths` first, then the roots."""
        roots = self.loader.roots or [pathlib.Path(DEFAULT_ROOT)]
        found: list = []
        for path in self.paths:
            if _is_anchored(path):
                found.append(path)
            else:
                found.extend(root / str(path) for root in roots)
        found.extend(roots)
        return found

    def find(self, name: "Names") -> Source:
        """Find the file for `name` and read its bytes.

        `name` may be a list of names: each is tried in turn, with all of its
        candidates in every search path, and the first file found wins.

        :raises TemplateNotFound: nothing matches, or a name has a `..` segment.
        """
        names = _names(name)
        for each in names:
            found = self._find_one(each)
            if found is not None:
                return found
        raise TemplateNotFound(names[0] if len(names) == 1 else names)

    def _find_one(self, name: str) -> "Optional[Source]":
        posix = PurePosixPath(name.lstrip("/"))
        parent = posix.parent.as_posix() if posix.parent != PurePosixPath(".") else None
        filename = posix.name
        names: List[str] = (
            list(self.candidates(filename)) if self.candidates else [filename]
        )
        directories = [
            directory / parent if parent is not None else directory
            for directory in self.search_paths()
        ]
        # Each directory is listed once per find, however many candidates.
        listings: Dict[int, Optional[_Listing]] = {}
        for candidate in names:
            for index, directory in enumerate(directories):
                if index not in listings:
                    listings[index] = _Listing.of(directory)
                listing = listings[index]
                if listing is None:
                    continue
                path = listing.match(candidate, self.loader.engines)
                if path is None:
                    continue
                if self.loader.sandbox:
                    # Refused before the file is read, by the suffix's engine.
                    for cls in self.loader.engines:
                        if can_process_suffix(cls, path):
                            self._check_sandbox(cls, _origin(path))
                            break
                data = path.read_bytes()
                mtime = path.stat().st_mtime

                def uptodate(path=path, mtime=mtime) -> bool:
                    try:
                        return path.stat().st_mtime == mtime
                    except OSError:
                        return False

                return Source(data, path.name, _origin(path), uptodate)
        return None

    def clear(self) -> None:
        """Forget the compiled templates and engine state; the next render resolves afresh.

        A cached template is reused while its own file is unchanged, so a more
        specific file added later is found only after this.
        """
        self._templates.clear()
        self._strings.clear()
        self._state.clear()

    def _check_sandbox(self, cls: type, what: str) -> None:
        """Refuse `cls` when the loader is sandboxed and the engine is not."""
        if self.loader.sandbox and not getattr(cls, "SANDBOXED", False):
            raise SandboxError(f"{what}: {cls.__name__} cannot run in a sandbox")

    def _engine_for(
        self, name: "Names", source: Source
    ) -> "Tuple[type, Union[str, bytes]]":
        """The engine that claims `source`, and the body it is built from."""
        try:
            text: "Optional[str]" = source.data.decode("utf-8")
            decode_error: "Optional[UnicodeDecodeError]" = None
        except UnicodeDecodeError as error:
            text, decode_error = None, error
        file = PurePosixPath(source.name)
        for cls in self.loader.engines:
            if not cls.can_process(file, source.data if text is None else text):
                continue
            self._check_sandbox(cls, source.origin)
            if cls.BINARY:
                return cls, source.data
            if text is None:
                raise NoEngineError(
                    f"{source.origin} is not valid UTF-8 text, which "
                    f"{cls.__name__} needs; only a BINARY engine can take bytes"
                ) from decode_error
            return cls, text
        claimed = "; ".join(
            f"{cls.__name__} ({', '.join(template_extensions(cls) or ('any suffix',))})"
            for cls in self.loader.engines
        )
        raise NoEngineError(
            f"no template engine handles {name!r} (found {source.origin}); "
            f"engines: {claimed or 'none configured'}"
        )

    def get(self, name: "Names") -> Template:
        """The compiled template for `name`, from the cache while its file is unchanged.

        :raises TemplateNotFound: no file matches.
        :raises NoEngineError: no engine claims the file, or it is not UTF-8
            and the engine that claims it needs text.
        :raises EngineUnavailableError: the claiming engine's extra or program
            is missing.
        :raises RenderError: the engine could not compile it.
        """
        cached = self._templates.get(_key(name))
        if cached is not None and cached.is_up_to_date:
            return cached
        source = self.find(name)
        cls, body = self._engine_for(name, source)
        try:
            template = cls(body, lookup=self, origin=source.origin)
        except TplxError:
            raise
        except Exception as exc:
            raise RenderError(
                f"{cls.__name__} could not compile {source.origin}: {exc}"
            ) from exc
        template._uptodate = source.uptodate
        self._templates[_key(name)] = template
        return template

    def resolve(self, name: "Names") -> "Tuple[Source, type]":
        """The file a render of `name` reads and the engine that renders it.

        :raises TemplateNotFound: no file matches.
        :raises NoEngineError: no engine claims the file.
        """
        source = self.find(name)
        return source, self._engine_for(name, source)[0]

    def include(self, name: str, engine: type) -> "Include":
        """Resolve an include written in an `engine` template.

        `name` is found and given an engine exactly as `get` would. When that
        engine is `engine` itself, `Include.text` holds the source for the
        including engine to compile natively (keeping its blocks, macros and
        context); otherwise it is `None`, and the engine inserts
        `render_include(name, values)` instead.
        """
        source = self.find(name)
        cls, body = self._engine_for(name, source)
        native = cls is engine and isinstance(body, str)
        return Include(source, cls, body if native else None)

    def render_include(self, name: str, values: "Mapping[str, Any]") -> str:
        """Render `name` with its own engine and `values`, as text to insert.

        :raises NoEngineError: the result is bytes that are not UTF-8.
        """
        rendered = self.render(name, {str(k): unwrap(v) for k, v in values.items()})
        if isinstance(rendered, bytes):
            try:
                return rendered.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise NoEngineError(
                    f"{name!r} renders bytes that are not UTF-8, which cannot be "
                    f"included in a text template"
                ) from exc
        return rendered

    def render(
        self,
        name: "Names",
        data: "Optional[Mapping[str, Any]]" = None,
        /,
        **overrides: Any,
    ) -> "Union[str, bytes]":
        """Render `name`; its names are the loader's globals, then `data`, then `overrides`.

        Text, or `bytes` from a `BINARY` engine.

        :raises RenderError: the engine failed; `UndefinedError` for a missing
            name in `strict` mode. Also everything `get` raises.
        """
        template = self.get(name)
        values = {**self.loader.globals, **(data or {}), **overrides}
        try:
            return template.render_values(values)
        except TplxError:
            raise
        except Exception as exc:
            raise RenderError(
                f"{type(template).__name__} failed to render {template.origin}: {exc}"
            ) from exc

    def evaluate(
        self,
        expression: str,
        context: "Optional[Mapping[str, Any]]" = None,
        /,
        *,
        engine: "Optional[EngineChoice]" = None,
        **overrides: Any,
    ) -> Any:
        """The value of `expression` in `engine`'s syntax, its type kept.

        `engine` is an engine class, its name or a suffix (`"jinja"`, `".j2"`,
        `"go"`), or `"python"`; by default `tplx.DEFAULT_ENGINE` (`"python"`,
        Python's own `eval`, which a sandbox refuses). The names are the
        loader's globals, then `context`, then `overrides`.

        :raises SandboxError: the loader is sandboxed and the engine is not.
        :raises UndefinedError: a missing name, under `strict`.
        :raises RenderError: the engine failed; `NotImplementedError` when it
            has no expressions.
        """
        choice = _engine_named(
            _default_engine() if engine is None else engine, self.loader.engines
        )
        values = {**self.loader.globals, **(context or {}), **overrides}
        if choice == PYTHON:
            if self.loader.sandbox:
                raise SandboxError(
                    "Python expressions cannot run in a sandbox; pass engine= one "
                    "that can (jinja, liquid, go, ...)"
                )
            try:
                return _python_evaluate(expression, values)
            except TplxError:
                raise
            except Exception as exc:
                raise RenderError(
                    f"python failed to evaluate {expression!r}: {exc}"
                ) from exc
        assert isinstance(choice, type)
        self._check_sandbox(choice, f"evaluate {expression!r}")
        try:
            return choice.evaluate(expression, values, lookup=self)
        except (TplxError, NotImplementedError):
            raise
        except Exception as exc:
            raise RenderError(
                f"{choice.__name__} failed to evaluate {expression!r}: {exc}"
            ) from exc

    def compile(
        self,
        source: "Union[str, bytes]",
        *,
        engine: "Optional[EngineChoice]" = None,
        name: str = "<string>",
    ) -> Template:
        """`source` compiled by `engine`, cached by engine and source.

        `engine` follows `evaluate`'s rule but must be a template engine (not
        `"python"`). Includes resolve through this lookup. At most
        `STRING_CACHE_SIZE` strings stay compiled.

        :raises SandboxError: the loader is sandboxed and the engine is not.
        :raises RenderError: the engine could not compile it.
        """
        choice = _engine_named(
            _default_engine() if engine is None else engine, self.loader.engines
        )
        if not isinstance(choice, type):
            raise ValueError(
                'compile needs a template engine: pass engine= ("python" '
                "only evaluates expressions)"
            )
        self._check_sandbox(choice, name)
        key = (choice, source, name)
        cached = self._strings.get(key)
        if cached is not None:
            self._strings.move_to_end(key)
            return cached
        body: "Union[str, bytes]" = source
        if choice.BINARY and isinstance(source, str):
            body = source.encode("utf-8")
        elif not choice.BINARY and isinstance(source, bytes):
            body = source.decode("utf-8")
        try:
            template = choice(body, lookup=self, origin=name)
        except TplxError:
            raise
        except Exception as exc:
            raise RenderError(
                f"{choice.__name__} could not compile {name}: {exc}"
            ) from exc
        self._strings[key] = template
        if len(self._strings) > STRING_CACHE_SIZE:
            self._strings.popitem(last=False)
        return template

    def state(self, key: Hashable, factory: Callable[[], Any]) -> Any:
        """Per-lookup state for an engine, built by `factory` on first use.

        An engine keeps what its includes need here (a jinja `Environment`, a
        mako `TemplateLookup`), so every template one lookup builds shares it.
        """
        try:
            return self._state[key]
        except KeyError:
            value = self._state[key] = factory()
            return value


_template.Lookup = Lookup

#: `evaluate`'s loaders, by sandbox, undefined mode and registry: they read no
#: file, and keep compiled expressions between calls.
_EVALUATORS: "Dict[Hashable, Loader]" = {}


def evaluate(
    expression: str,
    context: "Optional[Mapping[str, Any]]" = None,
    /,
    *,
    engine: "Optional[EngineChoice]" = None,
    sandbox: bool = False,
    undefined: str = "strict",
    **overrides: Any,
) -> Any:
    """The value of `expression` over `context`, with no loader to set up.

    `Loader.evaluate` on a loader that reads no file. `engine` defaults to
    `tplx.DEFAULT_ENGINE` (`"python"`); `sandbox=True` refuses `"python"` and
    every engine that is not `SANDBOXED`. A data name that is `engine`,
    `sandbox` or `undefined` goes in `context`.
    """
    key = (bool(sandbox), undefined, _registry.registered_engines())
    loader = _EVALUATORS.get(key)
    if loader is None:
        loader = _EVALUATORS[key] = Loader(
            [_NoFiles()], sandbox=sandbox, undefined=undefined
        )
    return loader.evaluate(expression, context, engine=engine, **overrides)
