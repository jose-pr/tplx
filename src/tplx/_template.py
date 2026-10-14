"""The engine contract every template class implements."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Mapping,
    Optional,
    Tuple,
    Union,
)

from ._encoder import DataEncoder
from ._registry import DEFAULT_PRIORITY, template_extensions

_DEFAULT_ENCODER = DataEncoder()

if TYPE_CHECKING:
    from ._loader import Lookup

#: How a template variable with no value renders: `strict` raises
#: `UndefinedError`, `lenient` renders an empty string, `debug` leaves the
#: placeholder in the output. An engine that cannot honour a mode says so in
#: its docstring.
UNDEFINED_MODES = ("strict", "lenient", "debug")


def can_process_suffix(cls, file) -> bool:
    """Is `file`'s suffix one `cls.EXT` claims? `file` is a path or a file name."""
    suffixes = template_extensions(cls)
    if suffixes is None:
        return True
    if isinstance(file, str):
        file = PurePosixPath(file)
    return str(getattr(file, "suffix", "")).lower() in suffixes


class Template:
    """A template an engine has compiled, ready to render.

    A subclass sets `EXT` (the suffixes it claims), optionally `PRIORITY` and
    `BINARY`, and implements `render_values`. The loader builds it with the file's
    contents, the `Lookup` that found it and the file's origin; an engine with
    an include syntax resolves includes through `self.lookup`, so they search
    the same roots as the file that includes them.
    """

    #: Suffixes this engine claims: `()` none, `None` (or `"*"`) every one.
    EXT: ClassVar[Union[None, str, Tuple[str, ...]]] = ()
    #: Engines are consulted highest first; see `DEFAULT_PRIORITY` and
    #: `FALLBACK_PRIORITY`.
    PRIORITY: ClassVar[int] = DEFAULT_PRIORITY
    #: True to receive the file's raw `bytes` and return `bytes`; False to
    #: receive UTF-8-decoded text.
    BINARY: ClassVar[bool] = False

    def __init__(
        self,
        source: "Union[str, bytes]",
        *,
        lookup: "Optional[Lookup]" = None,
        origin: str = "<string>",
    ) -> None:
        self.source = source
        self.lookup = lookup
        self.origin = origin
        self._uptodate: "Optional[Callable[[], bool]]" = None

    @property
    def undefined(self) -> str:
        """The `UNDEFINED_MODES` entry this template renders with."""
        return self.lookup.loader.undefined if self.lookup is not None else "strict"

    @property
    def encoder(self) -> "DataEncoder":
        """The `DataEncoder` this template presents its data with."""
        if self.lookup is not None:
            return self.lookup.loader.encoder
        return _DEFAULT_ENCODER

    @property
    def is_up_to_date(self) -> bool:
        """Is the file this was loaded from unchanged? True when there is no file."""
        check = self._uptodate
        return check() if check is not None else True

    def render(
        self, data: "Optional[Mapping[str, Any]]" = None, /, **overrides: Any
    ) -> "Union[str, bytes]":
        """Render with `data`, then `overrides`, as the template's top-level names.

        A keyword wins over the same name in `data`.
        """
        values = dict(data or {})
        values.update(overrides)
        return self.render_values(values)

    def render_values(self, values: "Mapping[str, Any]") -> "Union[str, bytes]":
        """What an engine implements: render with `values` as the top-level names."""
        raise NotImplementedError

    @classmethod
    def can_process(cls, file, source: "Union[str, bytes]") -> bool:
        """Does this engine render `file`? By default, when it claims the suffix."""
        return can_process_suffix(cls, file)
