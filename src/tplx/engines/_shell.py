"""The shell-style engine: `%{NAME}` placeholders (`.shtpl`), no dependency."""

from __future__ import annotations

import logging
import re
from typing import Any, ClassVar, Dict, Mapping, Tuple, Union

from .._template import Template
from ..exceptions import UndefinedError

LOGGER = logging.getLogger("tplx")

#: A placeholder name, matched case-insensitively: the data is flattened to
#: UPPER keys.
_IDENT = r"[_a-z][_a-z0-9]*"

#: Accepted `PATTERN` values: which spellings of a placeholder substitute.
PATTERNS = ("braced", "unbraced", "all")

#: The POSIX "use this when there is no value" operators, longest first. `:-`
#: counts an empty value as no value, `-` only an unset one.
DEFAULT_OPERATORS = (":-", "-")


class ShellTemplate(Template):
    """`%{UPPER_SNAKE}` placeholders substituted from the flattened data.

    The data is flattened by the loader's `DataEncoder.flatten`: by default
    nested names join with `_` and are upper-cased (`{"target": {"hostname":
    h}}` is `%{TARGET_HOSTNAME}`), `None` renders empty and a boolean as
    `true`/`false`. Placeholders match names case-insensitively. `%{NAME:-default}` and `%{NAME-default}` work as
    in POSIX shells, and `%%` is a literal `%`. Only the braced form is on by
    default, so a bare `%` is text: a kickstart keeps `%packages` and a script
    keeps `date +%Y%m%d`. All three undefined modes apply.

    Configured by subclassing:

    ```python
    class DollarTemplate(ShellTemplate):
        EXT = (".tpl", ".cfg")
        DELIMITER = "$"
        PATTERN = "all"         # ${NAME} and $NAME
    ```
    """

    EXT: ClassVar[Union[None, str, Tuple[str, ...]]] = (".shtpl",)
    #: What introduces a placeholder. Doubling it escapes it.
    DELIMITER: ClassVar[str] = "%"
    #: One of `PATTERNS`: `braced` for `%{NAME}` only, `unbraced` for `%NAME`
    #: only, `all` for both.
    PATTERN: ClassVar[str] = "braced"

    @classmethod
    def pattern(cls) -> "re.Pattern[str]":
        """The compiled placeholder pattern for this class.

        Cached in the class's own `__dict__`, so a subclass with another
        delimiter never reuses its parent's pattern.
        """
        cached = cls.__dict__.get("_compiled_pattern")
        if cached is not None:
            return cached
        if cls.PATTERN not in PATTERNS:
            raise ValueError(
                f"{cls.__name__}.PATTERN must be one of {', '.join(PATTERNS)}, "
                f"not {cls.PATTERN!r}"
            )
        delimiter = re.escape(str(cls.DELIMITER))
        operators = "|".join(re.escape(op) for op in DEFAULT_OPERATORS)
        # No `invalid` group: an unmatched delimiter stays literal text.
        alternatives = [rf"(?P<escaped>{delimiter})"]
        if cls.PATTERN in ("braced", "all"):
            alternatives.append(
                rf"\{{(?P<braced>{_IDENT})"
                rf"(?:(?P<operator>{operators})(?P<default>[^}}]*))?\}}"
            )
        if cls.PATTERN in ("unbraced", "all"):
            alternatives.append(rf"(?P<named>{_IDENT})")
        compiled = re.compile(
            delimiter + "(?:" + "|".join(alternatives) + ")", re.IGNORECASE
        )
        cls._compiled_pattern = compiled
        return compiled

    def variables(self, values: "Mapping[str, Any]") -> Dict[str, str]:
        """`values` as the placeholders read them: the encoder's `flatten`, by UPPER name."""
        return {key.upper(): text for key, text in self.encoder.flatten(values).items()}

    @staticmethod
    def _unquote(default: str) -> str:
        """Strip one layer of matching quotes: `%{NAME:-'a default'}`."""
        if len(default) >= 2 and default[0] == default[-1] and default[0] in "\"'":
            return default[1:-1]
        return default

    def render_values(self, values: "Mapping[str, Any]") -> str:
        variables = self.variables(values)
        mode = self.undefined

        def substitute(match: "re.Match[str]") -> str:
            groups = match.groupdict()
            if groups.get("escaped") is not None:
                return str(self.DELIMITER)
            name = groups.get("braced") or groups.get("named")
            operator = groups.get("operator")
            value = variables.get(name.upper())
            if operator is not None and (
                value is None or (operator == ":-" and value == "")
            ):
                return self._unquote(groups.get("default") or "")
            if value is not None:
                return value
            if mode == "debug":
                return match.group(0)
            if mode == "lenient":
                LOGGER.warning(
                    "shell template: %s has no value; rendering empty",
                    match.group(0),
                )
                return ""
            raise UndefinedError(f"{self.origin}: {match.group(0)} has no value")

        return self.pattern().sub(substitute, self.source)
