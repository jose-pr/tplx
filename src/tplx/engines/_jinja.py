"""Jinja (`.j2`, `.jinja`, `.jinja2`), behind the `jinja` extra."""

from __future__ import annotations

import re
import functools
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
from . import _bounds as bounds
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

    limits = lookup.loader.limits if lookup is not None else None
    if sandbox:
        Environment = _bounded_environment(limits.max_output if limits else 1_000_000)
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
    if sandbox:
        _bound_filters(environment, limits.max_output if limits else 1_000_000)
    return environment


def _bounded_environment(limit: int) -> type:
    """Jinja's immutable sandbox, refusing before it allocates past `limit`.

    `*`, `**`, `+` and `%` are checked on their operands (Jinja's
    `intercepted_binops`), `~` through `tplx_concat`, and a `str` method that
    builds by width or count before it is called; any value larger than
    `limit` is refused, so a value cannot grow step by step past it.
    """
    from jinja2.compiler import CodeGenerator
    from jinja2.sandbox import ImmutableSandboxedEnvironment

    class _Generator(CodeGenerator):
        def visit_Concat(self, node, frame) -> None:
            # `a ~ b` as `environment.tplx_concat((a, b))`, so it is checked.
            self.write("environment.tplx_concat((")
            for argument in node.nodes:
                self.visit(argument, frame)
                self.write(", ")
            self.write("))")

    class _Bounded(ImmutableSandboxedEnvironment):
        code_generator_class = _Generator
        intercepted_binops = frozenset({"*", "**", "+", "%"})

        def call_binop(self, context, operator, left, right):
            bounds.binop(operator, left, right, limit)
            result = super().call_binop(context, operator, left, right)
            return bounds.checked(result, limit)

        def call(__self, __context, __obj, *args, **kwargs):  # noqa: N805
            bounds.method_call(__obj, args, kwargs, limit)
            result = ImmutableSandboxedEnvironment.call(
                __self, __context, __obj, *args, **kwargs
            )
            return bounds.checked(result, limit)

        def tplx_concat(self, parts) -> str:
            texts = [str(part) for part in parts]
            bounds.refuse("a concatenation", sum(map(len, texts)), limit)
            return "".join(texts)

    return _Bounded


def _bound_filters(environment, limit: int) -> None:
    """Check the filters and globals that build by width or count, before they run."""

    def text_length(value) -> int:
        return len(value) if isinstance(value, str) else len(str(value))

    def center(value, width=80, *rest, **keywords):
        bounds.refuse("center", max(width, text_length(value)), limit)

    def indent(value, width=4, *rest, **keywords):
        step = len(width) if isinstance(width, str) else width
        lines = str(value).count("\n") + 1
        bounds.refuse("indent", text_length(value) + lines * max(step, 0), limit)

    def format_(value, *args, **keywords):
        bounds.format_widths(value, args + tuple(keywords.values()), limit)

    def replace(context, value, old, new, count=None):
        bounds.replace(str(value), old, new, -1 if count is None else count, limit)

    def join(context, value, d="", attribute=None):
        bounds.join(d, value, limit)

    def wordwrap(
        env, value, width=79, break_long_words=True, wrapstring=None, *rest, **keywords
    ):
        wrap = wrapstring if wrapstring is not None else env.newline_sequence
        breaks = text_length(value) // max(width, 1) + 1
        bounds.refuse("wordwrap", text_length(value) + breaks * len(wrap), limit)

    def guard(table, name, check) -> None:
        original = table.get(name)
        if original is None:
            return

        @functools.wraps(original)
        def guarded(*args, **keywords):
            check(*args, **keywords)
            return bounds.checked(original(*args, **keywords), limit)

        table[name] = guarded

    for name, check in (
        ("center", center),
        ("indent", indent),
        ("format", format_),
        ("replace", replace),
        ("join", join),
        ("wordwrap", wordwrap),
    ):
        guard(environment.filters, name, check)

    def lipsum(n=5, html=True, min=20, max=100):
        bounds.refuse("lipsum", n * max * 12, limit)

    guard(environment.globals, "lipsum", lipsum)


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
    `SandboxError`. `eval` gives one expression through Jinja's `compile_expression`.
    """

    EXT = (".j2", ".jinja", ".jinja2")
    _SYNTAX = re.compile(r"\{[{%#]")
    _EXPRESSION = ("{{", "}}", "-", "-")
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
    def _evaluate_expression(
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
            data = type(self)._data(self.lookup, values)
            limits = self.lookup.loader.limits if self.lookup is not None else None
            if limits is None:
                return self._template.render(data)
            parts, size = [], 0
            for part in self._template.generate(data):
                size += len(part)
                if size > limits.max_output:
                    raise SandboxError(
                        f"{self.origin}: output longer than {limits.max_output}"
                    )
                parts.append(part)
            return "".join(parts)
        except jinja2.UndefinedError as exc:
            raise UndefinedError(f"{self.origin}: {exc}") from exc
        except jinja2.exceptions.SecurityError as exc:
            raise SandboxError(f"{self.origin}: {exc}") from exc
        except jinja2.TemplateNotFound as exc:
            if isinstance(exc.__cause__, TemplateNotFound):
                raise exc.__cause__ from None
            raise TemplateNotFound(exc.name) from exc
