"""The root parser: the subcommands under one program name."""

from __future__ import annotations

from duho import AUTO, Args

from ..exceptions import TplxError
from .engines import Engines
from .find import Find
from .render import Render


class Tplx(Args):
    """Render templates with whichever engine each file's suffix names."""

    _parsername_ = "tplx"
    _version_ = AUTO
    _distribution_ = "tplx"
    _subcommands_ = [Render, Find, Engines]
    # A missing template or an engine failure is the operation failing, not the
    # invocation being wrong; a file that cannot be read or written is too.
    _errors_ = {TplxError: 1, OSError: 1}
