"""The shell-style engines: `%{NAME}` placeholders (`.shtpl`) and envsubst, no dependency."""

from __future__ import annotations

import logging
import re
from typing import Any, ClassVar, Dict, FrozenSet, List, Mapping, Optional, Tuple, Union

from .._loader import Lookup

from .._template import Template
from ..exceptions import SandboxError, UndefinedError

LOGGER = logging.getLogger("tplx")

#: A placeholder name, matched case-insensitively: the data is flattened to
#: UPPER keys.
_IDENT = r"[_a-zA-Z][_a-zA-Z0-9]*"
_NAME = re.compile(_IDENT)

#: Accepted `PATTERN` values: which spellings of a placeholder substitute.
PATTERNS = ("braced", "unbraced", "all")

#: Every syntax feature a shell-style engine can turn on in `FEATURES`
#: (`ShellTemplate.ALL_FEATURES`):
#:
#: - `escape`: a doubled delimiter is one literal delimiter (`%%`, `$$`).
#: - `default`: `{NAME-word}` (unset) and `{NAME:-word}` (unset or empty).
#: - `assign`: `{NAME=word}` and `{NAME:=word}`, read as `-` and `:-`.
#: - `alternate`: `{NAME+word}` (set) and `{NAME:+word}` (set and not empty).
#: - `nested`: a `word` is itself substituted (`{A:-{B}}`); else it is text.
#: - `unquote`: one layer of matching quotes is stripped from a `word`.
#: - `slice`: `{NAME:offset}` and `{NAME:offset:length}`, as bash (`{A: -2}`).
#: - `replace`: `{NAME/pattern/text}`, `//` every match, `/#` at the start,
#:   `/%` at the end; the pattern is a bash glob (`*`, `?`, `[...]`).
#: - `trim`: `{NAME#pattern}`, `##`, `%`, `%%`: remove the shortest or longest
#:   matching prefix or suffix.
#: - `case`: `{NAME^}`, `{NAME^^}`, `{NAME,}`, `{NAME,,}`.
#: - `length`: `{#NAME}`.
_FEATURES = frozenset(
    {
        "escape",
        "default",
        "assign",
        "alternate",
        "nested",
        "unquote",
        "slice",
        "replace",
        "trim",
        "case",
        "length",
    }
)

#: The envsubst implementations `EnvsubstTemplate.DIALECT` names
#: (`EnvsubstTemplate.DIALECTS`): which
#: placeholder spellings (`PATTERN`) and which `FEATURES` each one has.
_DIALECTS: Dict[str, Tuple[str, FrozenSet[str]]] = {
    # GNU gettext: `$NAME` and `${NAME}`, nothing else; `$$` stays `$$`.
    "gnu": ("all", frozenset()),
    # github.com/a8m/envsubst: POSIX defaults and alternates, `$$` escapes.
    "a8m": ("all", frozenset({"escape", "default", "assign", "alternate", "nested"})),
    # github.com/drone/envsubst: braced only, bash string functions.
    "drone": (
        "braced",
        frozenset(
            {
                "escape",
                "default",
                "assign",
                "nested",
                "slice",
                "replace",
                "trim",
                "case",
                "length",
            }
        ),
    ),
}

_SLICE = re.compile(
    r":\s*(?:\(\s*(?P<paren>-?\d+)\s*\)|(?P<offset>\d+|\s-\d+))"
    r"(?::\s*(?P<length>-?\d+))?\s*"
)


def _glob(pattern: str, *, lazy: bool = False) -> "re.Pattern[str]":
    """A bash pattern as a regex: `*`, `?`, `[...]` (`[!...]`), `\\x` for `x`."""
    parts: List[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\" and index + 1 < len(pattern):
            parts.append(re.escape(pattern[index + 1]))
            index += 2
            continue
        if char == "*":
            parts.append(".*?" if lazy else ".*")
        elif char == "?":
            parts.append(".")
        elif char == "[":
            close = pattern.find("]", index + 2)
            if close < 0:
                parts.append(re.escape(char))
            else:
                body = pattern[index + 1 : close].replace("\\", "\\\\")
                if body.startswith("!"):
                    body = "^" + body[1:]
                parts.append("[" + body + "]")
                index = close + 1
                continue
        else:
            parts.append(re.escape(char))
        index += 1
    return re.compile("".join(parts), re.DOTALL)


def _split_unescaped(text: str, separator: str) -> Tuple[str, Optional[str]]:
    """`text` split at its first `separator` not preceded by a backslash."""
    index = 0
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == separator:
            return text[:index], text[index + 1 :]
        index += 1
    return text, None


def _substitute(
    value: str, kind: str, pattern: str, text: str, limit: Optional[int] = None
) -> str:
    """bash `${v/p/t}` (`kind` ""), `${v//p/t}` ("/"), `${v/#p/t}` ("#"), `${v/%p/t}` ("%").

    With a `limit` (a sandbox's), the result may not grow past it.
    """
    if not pattern:
        return value
    if kind == "#":
        found = _glob(pattern).match(value)
        return text + value[found.end() :] if found else value
    if kind == "%":
        found = re.compile("(?:" + _glob(pattern).pattern + r")\Z", re.DOTALL).search(
            value
        )
        return value[: found.start()] + text if found else value
    regex = _glob(pattern)
    parts: List[str] = []
    position = 0
    while position <= len(value):
        found = regex.search(value, position)
        if found is None:
            break
        if found.end() == found.start():  # an empty match replaces nothing
            if found.start() >= len(value):
                break
            parts.append(value[position : found.start() + 1])
            position = found.start() + 1
            continue
        parts.append(value[position : found.start()])
        parts.append(text)
        position = found.end()
        if limit is not None:
            grown = sum(map(len, parts)) + len(value) - position
            if grown > limit:
                raise SandboxError(
                    f"a replacement would be larger than the sandbox allows ({limit})"
                )
        if kind != "/":
            break
    parts.append(value[position:])
    return "".join(parts)


def _trim(value: str, operator: str, pattern: str) -> str:
    """bash `${v#p}`, `${v##p}`, `${v%p}`, `${v%%p}`."""
    if operator in ("#", "##"):
        found = _glob(pattern, lazy=operator == "#").match(value)
        return value[found.end() :] if found else value
    regex = _glob(pattern)
    starts = range(len(value), -1, -1) if operator == "%" else range(0, len(value) + 1)
    for start in starts:
        if regex.fullmatch(value, start):
            return value[:start]
    return value


def _slice(value: str, offset: int, length: Optional[int]) -> str:
    """bash `${v:offset:length}`: a negative offset counts from the end."""
    size = len(value)
    if offset < 0:
        offset += size
        if offset < 0:
            return ""
    if length is None:
        return value[offset:]
    end = offset + length if length >= 0 else size + length
    return value[offset:end] if end > offset else ""


class _Keep(Exception):
    """An undefined name in `debug` mode: the expression is written as it is."""


class ShellTemplate(Template):
    """`%{UPPER_SNAKE}` placeholders substituted from the flattened data.

    The data is flattened by the loader's `DataEncoder.flatten`: by default
    nested names join with `_` and are upper-cased (`{"target": {"hostname":
    h}}` is `%{TARGET_HOSTNAME}`), `None` renders empty and a boolean as
    `true`/`false`. Placeholders match names case-insensitively.
    `%{NAME:-default}` and `%{NAME-default}` work as in POSIX shells, as do
    `%{NAME:1:3}` (a slice) and `%{NAME//pattern/text}` (a replacement), and
    `%%` is a literal `%`. Only the braced form is on by default, so a bare `%`
    is text: a kickstart keeps `%packages` and a script keeps `date +%Y%m%d`.
    An expression it does not know (`%{NAME:?x}`) is text: its `%` is written
    and the scan goes on inside it. All three undefined modes apply.

    Configured by subclassing:

    ```python
    class CfgTemplate(ShellTemplate):
        EXT = (".tpl", ".cfg")
        DELIMITER = "$"
        PATTERN = "all"         # ${NAME} and $NAME
        FEATURES = ShellTemplate.FEATURES | {"trim", "case"}
    ```
    """

    EXT: ClassVar[Union[None, str, Tuple[str, ...]]] = (".shtpl",)
    SANDBOXED = True
    #: What introduces a placeholder. Doubling it escapes it (`escape`).
    DELIMITER: ClassVar[str] = "%"
    _EXPRESSION = ("%{", "}", "", "")

    def __init_subclass__(cls, **keywords: Any) -> None:
        super().__init_subclass__(**keywords)
        # A subclass with another delimiter has another expression, unless it says.
        if "_EXPRESSION" not in cls.__dict__:
            cls._EXPRESSION = (str(cls.DELIMITER) + "{", "}", "", "")

    @classmethod
    def is_template(cls, text: str) -> bool:
        """Does `text` hold a placeholder: the delimiter before `{` (or a name,
        when the bare form is on)? A doubled delimiter alone does not count."""
        pattern = cls.__dict__.get("_syntax_pattern")
        if pattern is None:
            form, _ = cls.syntax()
            delimiter = re.escape(str(cls.DELIMITER))
            starts = [r"\{"] if form in ("braced", "all") else []
            if form in ("unbraced", "all"):
                starts.append("[A-Za-z_]")
            pattern = re.compile(delimiter + "(?:" + "|".join(starts) + ")")
            cls._syntax_pattern = pattern
        return pattern.search(text) is not None

    #: One of `PATTERNS`: `braced` for `%{NAME}` only, `unbraced` for `%NAME`
    #: only, `all` for both.
    PATTERN: ClassVar[Optional[str]] = "braced"
    #: Every feature `FEATURES` may name.
    ALL_FEATURES: ClassVar[FrozenSet[str]] = _FEATURES
    #: The syntax features on, a subset of `ALL_FEATURES`.
    FEATURES: ClassVar[Optional[FrozenSet[str]]] = frozenset(
        {"escape", "default", "unquote", "slice", "replace"}
    )

    @classmethod
    def syntax(cls) -> Tuple[str, FrozenSet[str]]:
        """This class's `(PATTERN, FEATURES)`, checked.

        :raises ValueError: an unknown `PATTERN` or feature.
        """
        cached = cls.__dict__.get("_syntax")
        if cached is not None:
            return cached
        pattern, features = cls.PATTERN, cls.FEATURES
        if pattern is None or features is None:
            raise ValueError(f"{cls.__name__} sets no PATTERN or FEATURES")
        if pattern not in PATTERNS:
            raise ValueError(
                f"{cls.__name__}.PATTERN must be one of {', '.join(PATTERNS)}, "
                f"not {pattern!r}"
            )
        unknown = set(features) - _FEATURES
        if unknown:
            raise ValueError(
                f"{cls.__name__}.FEATURES has unknown {sorted(unknown)}; "
                f"known: {', '.join(sorted(_FEATURES))}"
            )
        cls._syntax = (pattern, frozenset(features))
        return cls._syntax

    @classmethod
    def pattern(cls) -> "re.Pattern[str]":
        """A pattern finding where a placeholder starts (`escaped`, `braced`, `named`).

        Cached in the class's own `__dict__`, so a subclass with another
        delimiter never reuses its parent's pattern.
        """
        cached = cls.__dict__.get("_compiled_pattern")
        if cached is not None:
            return cached
        pattern, _ = cls.syntax()
        delimiter = re.escape(str(cls.DELIMITER))
        alternatives = [rf"(?P<escaped>{delimiter})"]
        if pattern in ("braced", "all"):
            alternatives.append(rf"\{{(?P<braced>{_IDENT})")
        if pattern in ("unbraced", "all"):
            alternatives.append(rf"(?P<named>{_IDENT})")
        compiled = re.compile(delimiter + "(?:" + "|".join(alternatives) + ")")
        cls._compiled_pattern = compiled
        return compiled

    @classmethod
    def _evaluate_expression(
        cls,
        expression: str,
        values: "Mapping[str, Any]",
        *,
        lookup: "Optional[Lookup]" = None,
    ) -> Any:
        """What goes between the braces (`HOST`, `HOST:-x`, `PATH//:/ `), as text.

        :raises ValueError: an expression this syntax does not know.
        """
        template = cls("", lookup=lookup)
        whole = f"{cls.DELIMITER}{{{expression}}}"
        found = template._braced(expression, whole, template.variables(values))
        if found is None:
            raise ValueError(f"{cls.__name__} does not know {whole!r}")
        return found

    def references(self) -> FrozenSet[str]:
        """The placeholder names this template reads, as written."""
        names = set()
        for match in self.pattern().finditer(self.source):
            name = match.group("braced") or match.groupdict().get("named")
            if name:
                names.add(name)
        return frozenset(names)

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
        return self.expand(self.source, self.variables(values))

    def expand(self, text: str, variables: "Mapping[str, str]") -> str:
        """`text` with every placeholder substituted from `variables` (UPPER names)."""
        pattern, features = self.syntax()
        delimiter = str(self.DELIMITER)
        braced = pattern in ("braced", "all")
        unbraced = pattern in ("unbraced", "all")
        parts: List[str] = []
        position = 0
        while True:
            start = text.find(delimiter, position)
            if start < 0:
                parts.append(text[position:])
                return "".join(parts)
            parts.append(text[position:start])
            after = start + len(delimiter)
            if "escape" in features and text.startswith(delimiter, after):
                parts.append(delimiter)
                position = after + len(delimiter)
                continue
            if braced and text.startswith("{", after):
                close = self._closing(text, after + 1, delimiter)
                if close is not None:
                    whole = text[start : close + 1]
                    found = self._braced(text[after + 1 : close], whole, variables)
                    if found is not None:
                        parts.append(found)
                        position = close + 1
                        continue
            if unbraced:
                name = _NAME.match(text, after)
                if name is not None:
                    whole = text[start : name.end()]
                    parts.append(self._value_or_keep(name.group(), whole, variables))
                    position = name.end()
                    continue
            parts.append(delimiter)
            position = after

    @staticmethod
    def _closing(text: str, index: int, delimiter: str) -> Optional[int]:
        """Where the `}` closing a brace opened just before `index` is, if any."""
        depth = 0
        opener = delimiter + "{"
        while index < len(text):
            if text.startswith(opener, index):
                depth += 1
                index += len(opener)
                continue
            if text[index] == "}":
                if depth == 0:
                    return index
                depth -= 1
            index += 1
        return None

    def _value_or_keep(
        self, name: str, whole: str, variables: "Mapping[str, str]"
    ) -> str:
        try:
            return self._value(name, whole, variables)
        except _Keep:
            return whole

    def _value(self, name: str, whole: str, variables: "Mapping[str, str]") -> str:
        """The value of `name`, or what the undefined mode makes of `whole`."""
        value = variables.get(name.upper())
        if value is not None:
            return value
        mode = self.undefined
        if mode == "debug":
            raise _Keep
        if mode == "lenient":
            LOGGER.warning("shell template: %s has no value; rendering empty", whole)
            return ""
        raise UndefinedError(f"{self.origin}: {whole} has no value")

    def _word(self, word: str, variables: "Mapping[str, str]") -> str:
        """A default's or alternate's text, as `nested` and `unquote` say."""
        _, features = self.syntax()
        if "nested" in features:
            word = self.expand(word, variables)
        if "unquote" in features:
            word = self._unquote(word)
        return word

    def _braced(
        self, body: str, whole: str, variables: "Mapping[str, str]"
    ) -> Optional[str]:
        """The text for `{body}`, or None for an expression this syntax does not know.

        An unknown expression is text: its delimiter is written and the scan
        goes on inside it, as GNU envsubst does (`${U:-$B}` keeps `${U:-`).
        """
        _, features = self.syntax()
        try:
            if "length" in features and body.startswith("#"):
                name = _NAME.fullmatch(body, 1)
                if name is not None:
                    return str(len(self._value(name.group(), whole, variables)))
            name = _NAME.match(body)
            if name is None:
                return None
            key, rest = name.group(), body[name.end() :]
            if not rest:
                return self._value(key, whole, variables)
            value = variables.get(key.upper())
            for operator, feature in (
                (":-", "default"),
                (":=", "assign"),
                (":+", "alternate"),
                ("-", "default"),
                ("=", "assign"),
                ("+", "alternate"),
            ):
                if rest.startswith(operator):
                    if feature not in features:
                        return None
                    word = rest[len(operator) :]
                    empty_counts = operator.startswith(":")
                    present = value is not None and not (empty_counts and value == "")
                    if operator.endswith("+"):
                        return self._word(word, variables) if present else ""
                    return value if present else self._word(word, variables)
            if rest.startswith(":"):
                found = _SLICE.fullmatch(rest)
                if "slice" not in features or found is None:
                    return None
                offset = int(found.group("paren") or found.group("offset"))
                length = found.group("length")
                value = self._value(key, whole, variables)
                return _slice(value, offset, None if length is None else int(length))
            if rest.startswith("/"):
                if "replace" not in features:
                    return None
                spec = rest[1:]
                kind = spec[:1] if spec[:1] in ("/", "#", "%") else ""
                pattern, text = _split_unescaped(spec[len(kind) :], "/")
                value = self._value(key, whole, variables)
                limits = self.lookup.loader.limits if self.lookup else None
                return _substitute(
                    value,
                    kind,
                    pattern,
                    text or "",
                    limits.max_output if limits else None,
                )
            if rest[:1] in ("#", "%"):
                if "trim" not in features:
                    return None
                operator = rest[:2] if rest[:2] in ("##", "%%") else rest[:1]
                value = self._value(key, whole, variables)
                return _trim(value, operator, rest[len(operator) :])
            if rest in ("^", "^^", ",", ",,"):
                if "case" not in features:
                    return None
                value = self._value(key, whole, variables)
                if rest == "^^":
                    return value.upper()
                if rest == ",,":
                    return value.lower()
                head = value[:1].upper() if rest == "^" else value[:1].lower()
                return head + value[1:]
            return None
        except _Keep:
            return whole


class DollarTemplate(ShellTemplate):
    """The shell syntax with `$`: `${HOST}`, `${PORT:-80}`, `${PATH//:/ }`, `$$`.

    `tplx.DEFAULT_ENGINE`, for `eval` and `compile` given no engine. Only
    the braced form, so `cost $5` and `$HOME` are text. Not registered: no
    file suffix picks it (`.shtpl` is `%`, `.envsubst` is `EnvsubstTemplate`).
    """

    EXT: ClassVar[Union[None, str, Tuple[str, ...]]] = ()
    DELIMITER: ClassVar[str] = "$"


class EnvsubstTemplate(ShellTemplate):
    """`$NAME` and `${NAME}` as envsubst writes them (`.envsubst`, `.template`).

    `DIALECT` picks which envsubst it reads like, from `DIALECTS`: `gnu` (the
    default: no defaults, no `$$` escape, an expression it does not know is
    left as it is), `a8m` (POSIX defaults and alternates, `$$` escapes) or
    `drone` (braced only; defaults, slices, replacements, trims, case, length).
    Setting `PATTERN` or `FEATURES` in a subclass overrides the dialect's.
    Values come from the render's data, flattened as for the shell engine
    (pass `os.environ` as data, or `tplx render --env`); names match
    case-insensitively, and an undefined name follows the undefined mode
    (`debug` keeps it, as nginx's own `$uri` should be).

    ```python
    class DroneEnvsubst(EnvsubstTemplate):
        DIALECT = "drone"
    ```
    """

    EXT: ClassVar[Union[None, str, Tuple[str, ...]]] = (".envsubst", ".template")
    DELIMITER: ClassVar[str] = "$"
    #: Each dialect's `(PATTERN, FEATURES)`.
    DIALECTS: ClassVar[Dict[str, Tuple[str, FrozenSet[str]]]] = _DIALECTS
    #: One of `DIALECTS`.
    DIALECT: ClassVar[str] = "gnu"
    PATTERN: ClassVar[Optional[str]] = None
    FEATURES: ClassVar[Optional[FrozenSet[str]]] = None

    @classmethod
    def syntax(cls) -> Tuple[str, FrozenSet[str]]:
        """`PATTERN` and `FEATURES`, each the dialect's unless the class sets it.

        :raises ValueError: an unknown `DIALECT`, `PATTERN` or feature.
        """
        cached = cls.__dict__.get("_syntax")
        if cached is not None:
            return cached
        if cls.DIALECT not in cls.DIALECTS:
            raise ValueError(
                f"{cls.__name__}.DIALECT must be one of {', '.join(cls.DIALECTS)}, "
                f"not {cls.DIALECT!r}"
            )
        pattern, features = cls.DIALECTS[cls.DIALECT]
        resolved = type(
            cls.__name__,
            (ShellTemplate,),
            {
                "PATTERN": cls.PATTERN if cls.PATTERN is not None else pattern,
                "FEATURES": cls.FEATURES if cls.FEATURES is not None else features,
            },
        ).syntax()
        cls._syntax = resolved
        return resolved
