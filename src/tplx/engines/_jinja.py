"""Jinja (`.j2`, `.jinja`, `.jinja2`), behind the `jinja` extra."""

from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any, FrozenSet, Mapping, Optional

from .._loader import Lookup
from .._template import Template
from ..exceptions import (
    EngineUnavailableError,
    SandboxError,
    TemplateNotFound,
    UndefinedError,
)
from ._capture import cached

#: The global a stub calls to render another engine's file.
INCLUDE_NAME = "__tplx_include__"
_MISSING = object()


def _jinja2():
    try:
        import jinja2
    except ImportError as exc:
        raise EngineUnavailableError(
            "the jinja template engine needs the 'jinja' extra: "
            "pip install tplx[jinja]"
        ) from exc
    return jinja2


def _environment(
    jinja2, lookup: "Optional[Lookup]", engine: type, mode: str, sandbox: bool
):
    """A jinja `Environment` whose includes resolve through `lookup`; a
    `SandboxedEnvironment` when `sandbox`."""
    undefined = {
        "strict": jinja2.StrictUndefined,
        "lenient": jinja2.Undefined,
        "debug": jinja2.DebugUndefined,
    }[mode]

    class _LookupLoader(jinja2.BaseLoader):
        def get_source(self, environment, name):
            if lookup is None:
                raise jinja2.TemplateNotFound(name)
            try:
                found = lookup.include(name, engine)
            except TemplateNotFound as exc:
                raise jinja2.TemplateNotFound(name) from exc
            source = found.source
            if found.text is not None:
                return found.text, source.origin, source.uptodate
            # Another engine's file: a stub that renders it with this context.
            stub = "{{ %s(%s) }}" % (INCLUDE_NAME, json.dumps(name))
            return stub, source.origin, source.uptodate

    if sandbox:
        from jinja2.sandbox import ImmutableSandboxedEnvironment as Environment
    else:
        Environment = jinja2.Environment
    environment = Environment(
        loader=_LookupLoader(),
        undefined=undefined,
        # Artifacts are line-oriented files; the last line keeps its newline,
        # as it does in every other engine.
        keep_trailing_newline=True,
    )
    builtins = dict(environment.globals)

    @jinja2.pass_context
    def include(context, name: str) -> str:
        values = {
            key: value
            for key, value in context.get_all().items()
            if key != INCLUDE_NAME and builtins.get(key, _MISSING) is not value
        }
        return lookup.render_include(name, values)

    environment.globals[INCLUDE_NAME] = include
    return environment


class JinjaTemplate(Template):
    """A Jinja template. Needs the **`jinja` extra**.

    `{% include %}`, `{% extends %}`, `{% import %}` and `{% from %}` resolve
    through the `Lookup` that loaded the file, exactly as a render would: a
    Jinja file is compiled by Jinja, any other is rendered by its own engine
    with the current context and its output inserted. All three undefined
    modes apply. Output keeps the template's trailing newline and, as Jinja
    does by default, writes every line ending as LF. In a sandboxed loader the
    environment is Jinja's `ImmutableSandboxedEnvironment` and the data is
    plain (`DataEncoder.wrap(plain=True)`): an unsafe attribute or call raises
    `SandboxError`. `evaluate` is Jinja's `compile_expression`.
    """

    EXT = (".j2", ".jinja", ".jinja2")
    SANDBOXED = True

    @classmethod
    def environment(cls, lookup: "Optional[Lookup]" = None) -> Any:
        """The Jinja environment `lookup`'s templates share (configured, sandboxed)."""
        jinja2 = _jinja2()
        mode = lookup.loader.undefined if lookup is not None else "strict"
        sandbox = lookup is not None and lookup.loader.sandbox

        def factory():
            return cls.configured(
                lookup, _environment(jinja2, lookup, cls, mode, sandbox)
            )

        if lookup is None:
            return factory()
        return lookup.state(("jinja", cls, mode, sandbox), factory)

    @classmethod
    def evaluate(
        cls,
        expression: str,
        values: "Mapping[str, Any]",
        *,
        lookup: "Optional[Lookup]" = None,
    ) -> Any:
        jinja2 = _jinja2()
        environment = cls.environment(lookup)
        build = lambda: environment.compile_expression(  # noqa: E731
            expression, undefined_to_none=False
        )
        if lookup is None:
            compiled = build()
        else:
            cache = lookup.state(("jinja-expressions", cls), OrderedDict)
            compiled = cached(cache, expression, build)
        try:
            result = compiled(**cls._data(lookup, values))
        except jinja2.UndefinedError as exc:
            raise UndefinedError(f"{expression!r}: {exc}") from exc
        except jinja2.exceptions.SecurityError as exc:
            raise SandboxError(f"{expression!r}: {exc}") from exc
        if isinstance(result, jinja2.Undefined):
            if lookup is None or lookup.loader.undefined == "strict":
                raise UndefinedError(f"{expression!r}: {result._undefined_message}")
            return None
        return result

    @classmethod
    def _data(cls, lookup: "Optional[Lookup]", values: "Mapping[str, Any]") -> Any:
        """The data as Jinja reads it: as it is, or plain in a sandbox (no
        method of the caller's objects reachable)."""
        if lookup is not None and lookup.loader.sandbox:
            return lookup.loader.encoder.view(values, plain=True)
        return {str(k): v for k, v in values.items()}

    def references(self) -> FrozenSet[str]:
        from jinja2 import meta

        return frozenset(
            meta.find_undeclared_variables(self._environment.parse(self.source))
        )

    def __init__(
        self,
        source: str,
        *,
        lookup: "Optional[Lookup]" = None,
        origin: str = "<string>",
    ) -> None:
        super().__init__(source, lookup=lookup, origin=origin)
        self._jinja2 = _jinja2()
        environment = self._environment = type(self).environment(lookup)
        code = environment.compile(source, name=origin, filename=origin)
        self._template = environment.template_class.from_code(
            environment, code, environment.make_globals(None), None
        )

    def render_values(self, values: "Mapping[str, Any]") -> str:
        jinja2 = self._jinja2
        try:
            return self._template.render(type(self)._data(self.lookup, values))
        except jinja2.UndefinedError as exc:
            raise UndefinedError(f"{self.origin}: {exc}") from exc
        except jinja2.exceptions.SecurityError as exc:
            raise SandboxError(f"{self.origin}: {exc}") from exc
        except jinja2.TemplateNotFound as exc:
            if isinstance(exc.__cause__, TemplateNotFound):
                raise exc.__cause__ from None
            raise TemplateNotFound(exc.name) from exc
