"""The shipped engines, registered on import.

An optional engine is registered whether or not its library is installed: a
`.mako` file without the extra raises `EngineUnavailableError` naming it,
rather than being copied as bytes because nothing claimed it. Importing this
package imports no engine library.
"""

from __future__ import annotations

from .._registry import register_engine
from ._cheetah import CheetahTemplate
from ._copy import CopyTemplate
from ._external import EPPTemplate, ERBTemplate, SubprocessTemplate
from ._go import GoTemplate
from ._handlebars import HandlebarsTemplate
from ._jinja import JinjaTemplate
from ._liquid import LiquidTemplate
from ._mako import MakoTemplate
from ._mustache import MustacheTemplate
from ._shell import EnvsubstTemplate, ShellTemplate

__all__ = [
    "CheetahTemplate",
    "CopyTemplate",
    "EnvsubstTemplate",
    "EPPTemplate",
    "ERBTemplate",
    "GoTemplate",
    "HandlebarsTemplate",
    "JinjaTemplate",
    "LiquidTemplate",
    "MakoTemplate",
    "MustacheTemplate",
    "ShellTemplate",
    "SubprocessTemplate",
]

for _engine in (
    JinjaTemplate,
    MakoTemplate,
    LiquidTemplate,
    HandlebarsTemplate,
    MustacheTemplate,
    GoTemplate,
    CheetahTemplate,
    ERBTemplate,
    EPPTemplate,
    ShellTemplate,
    EnvsubstTemplate,
    CopyTemplate,
):
    register_engine(_engine)
del _engine
