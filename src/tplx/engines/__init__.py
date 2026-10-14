"""The shipped engines, registered on import.

An optional engine is registered whether or not its library is installed: a
`.mako` file without the extra raises `EngineUnavailableError` naming it,
rather than being copied as bytes because nothing claimed it. Importing this
package imports no engine library.
"""

from .._registry import register_engine
from ._copy import CopyTemplate
from ._external import EPPTemplate, ERBTemplate, SubprocessTemplate
from ._handlebars import HandlebarsTemplate
from ._jinja import JinjaTemplate
from ._liquid import LiquidTemplate
from ._mako import MakoTemplate
from ._mustache import MustacheTemplate
from ._shell import ShellTemplate

__all__ = [
    "CopyTemplate",
    "EPPTemplate",
    "ERBTemplate",
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
    ERBTemplate,
    EPPTemplate,
    ShellTemplate,
    CopyTemplate,
):
    register_engine(_engine)
del _engine
