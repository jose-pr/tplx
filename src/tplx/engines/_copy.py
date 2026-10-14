"""The catch-all engine: a file no other engine claims is returned byte for byte."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from .._registry import FALLBACK_PRIORITY, template_extensions
from .._template import Template
from ._shell import ShellTemplate

LOGGER = logging.getLogger("tplx")


def _has_shell_placeholders(source: bytes) -> bool:
    """Does `source` hold a `%{NAME}` placeholder (not just an escaped `%%`)?"""
    text = source.decode("utf-8", errors="ignore")
    for match in ShellTemplate.pattern().finditer(text):
        groups = match.groupdict()
        if groups.get("braced") or groups.get("named"):
            return True
    return False


class CopyTemplate(Template):
    """Return the file's **bytes**, unchanged; claims every suffix, consulted last.

    `BINARY`, so the file is never decoded: a CRLF file, latin-1 text or an
    EFI binary all come back exactly as stored, and `render` returns `bytes`.
    A file that still holds `%{NAME}` placeholders logs a warning, since it was
    probably meant for the shell engine.
    """

    EXT = None
    PRIORITY = FALLBACK_PRIORITY
    BINARY = True

    def __init__(
        self, source: "bytes | str", *, lookup=None, origin: str = "<string>"
    ) -> None:
        if not isinstance(source, bytes):
            source = str(source).encode("utf-8")
        super().__init__(source, lookup=lookup, origin=origin)

    def render_values(self, values: "Mapping[str, Any]") -> bytes:
        if _has_shell_placeholders(self.source):
            suffix = (template_extensions(ShellTemplate) or (".shtpl",))[0]
            LOGGER.warning(
                "%s is copied as is but contains %s placeholders; name it *%s "
                "for them to be substituted",
                self.origin,
                ShellTemplate.DELIMITER + "{NAME}",
                suffix,
            )
        return self.source
