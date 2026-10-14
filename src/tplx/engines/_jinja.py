"""Jinja (`.j2`, `.jinja`, `.jinja2`), behind the `jinja` extra."""

from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from .._loader import Lookup
from .._template import Template
from ..exceptions import EngineUnavailableError, TemplateNotFound, UndefinedError

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


def _environment(jinja2, lookup: "Optional[Lookup]", engine: type, mode: str):
    """A jinja `Environment` whose includes resolve through `lookup`."""
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

    environment = jinja2.Environment(
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
    does by default, writes every line ending as LF.
    """

    EXT = (".j2", ".jinja", ".jinja2")

    def __init__(
        self,
        source: str,
        *,
        lookup: "Optional[Lookup]" = None,
        origin: str = "<string>",
    ) -> None:
        super().__init__(source, lookup=lookup, origin=origin)
        jinja2 = self._jinja2 = _jinja2()
        mode = self.undefined
        key = ("jinja", type(self), mode)

        def factory():
            return _environment(jinja2, lookup, type(self), mode)

        environment = lookup.state(key, factory) if lookup is not None else factory()
        code = environment.compile(source, name=origin, filename=origin)
        self._template = environment.template_class.from_code(
            environment, code, environment.make_globals(None), None
        )

    def render_values(self, values: "Mapping[str, Any]") -> str:
        jinja2 = self._jinja2
        try:
            return self._template.render(values)
        except jinja2.UndefinedError as exc:
            raise UndefinedError(f"{self.origin}: {exc}") from exc
        except jinja2.TemplateNotFound as exc:
            if isinstance(exc.__cause__, TemplateNotFound):
                raise exc.__cause__ from None
            raise TemplateNotFound(exc.name) from exc
