"""tplx: render a tree of templates with whichever engine each file's suffix names."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

from ._encoder import DataEncoder, DataView
from ._loader import DEFAULT_ROOT, Include, Loader, Lookup, Source
from ._registry import (
    ANY_SUFFIX,
    DEFAULT_PRIORITY,
    ENTRY_POINT_GROUP,
    FALLBACK_PRIORITY,
    by_priority,
    registered_engines,
    register_engine,
    template_extensions,
    unregister_engine,
)
from ._template import UNDEFINED_MODES, Template, can_process_suffix
from .engines import (
    CopyTemplate,
    EPPTemplate,
    ERBTemplate,
    HandlebarsTemplate,
    JinjaTemplate,
    LiquidTemplate,
    MakoTemplate,
    MustacheTemplate,
    ShellTemplate,
    SubprocessTemplate,
)
from .exceptions import (
    EngineUnavailableError,
    NoEngineError,
    RenderError,
    RenderTimeoutError,
    TemplateNotFound,
    TplxError,
    UndefinedError,
)

try:
    __version__ = _version("tplx")
except PackageNotFoundError:  # pragma: no cover - never-installed source tree
    __version__ = "0.0.0"

__all__ = [
    "__version__",
    # loading
    "Loader",
    "Lookup",
    "Source",
    "Include",
    "DEFAULT_ROOT",
    "DataEncoder",
    "DataView",
    # the engine contract and registry
    "Template",
    "UNDEFINED_MODES",
    "can_process_suffix",
    "register_engine",
    "unregister_engine",
    "registered_engines",
    "by_priority",
    "template_extensions",
    "ANY_SUFFIX",
    "DEFAULT_PRIORITY",
    "FALLBACK_PRIORITY",
    "ENTRY_POINT_GROUP",
    # shipped engines
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
    # errors
    "TplxError",
    "TemplateNotFound",
    "NoEngineError",
    "EngineUnavailableError",
    "RenderError",
    "UndefinedError",
    "RenderTimeoutError",
]
