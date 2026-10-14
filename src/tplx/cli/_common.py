"""What the commands share: where templates are looked for, and how."""

from __future__ import annotations

import json
import os
import typing as _ty

from duho import Cmd, LoggingArgs, UsageError

from .._loader import Loader, Lookup


class Command(LoggingArgs, Cmd):
    """Options every command takes: the roots, the search paths, the undefined mode."""

    _logger_name_ = "tplx"

    roots: _ty.List[str] = []
    "A template root, searched in order; repeat for more (default: ./templates, or the file's own directory)"
    ("--root", "-r")

    paths: _ty.List[str] = []
    "A directory searched before the roots: absolute, or inside each root; repeat for more"
    ("--path", "-p")

    undefined: _ty.Literal["strict", "lenient", "debug"] = "strict"
    "What a name the data does not define renders as"
    ("--undefined", "-u")

    def resolve(self, name: str) -> "_ty.Tuple[Lookup, str]":
        """The lookup to use and the name to ask it for.

        With no `--root`, a `name` that is an existing file is that file: its
        directory is the root and its file name the name.
        """
        roots = list(self.roots)
        if not roots and os.path.isfile(name):
            directory, name = os.path.split(os.path.abspath(name))
            roots = [directory]
        loader = Loader(roots, undefined=self.undefined)
        return loader.lookup(paths=self.paths), name


def merge(base: "_ty.Dict[str, _ty.Any]", over: "_ty.Mapping[str, _ty.Any]") -> dict:
    """`over` merged into `base`, nested objects key by key; `base` is updated."""
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        else:
            base[key] = value
    return base


def parse_assignments(assignments: "_ty.Iterable[str]") -> "_ty.Dict[str, _ty.Any]":
    """`key=value` items as nested data: `a.b=1` is `{"a": {"b": "1"}}`.

    A value is text, unless it starts with `json:`, when the rest is JSON
    (`n=json:3`, `servers=json:["a","b"]`).

    :raises UsageError: an item without `=`, or `json:` text that is not JSON.
    """
    data: _ty.Dict[str, _ty.Any] = {}
    for item in assignments:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise UsageError(f"--set takes key=value, not {item!r}")
        parsed: _ty.Any = value
        if value.startswith("json:"):
            try:
                parsed = json.loads(value[len("json:") :])
            except ValueError as exc:
                raise UsageError(f"--set {key}: not JSON: {exc}") from exc
        *parents, leaf = key.split(".")
        node = data
        for part in parents:
            child = node.get(part)
            if not isinstance(child, dict):
                child = node[part] = {}
            node = child
        node[leaf] = parsed
    return data
