"""`tplx render`: render a template, by name or as a file."""

from __future__ import annotations

import json
import sys
import typing as _ty

from duho import UsageError

from ._common import Command, merge, parse_assignments


class Render(Command):
    """Render a template with the data given, to standard output or a file."""

    _parsername_ = "render"
    _examples_ = [
        ("tplx render templates/boot.cfg.j2 -s hostname=web01", "render one file"),
        ("tplx render boot.cfg -r templates -d host.json", "render a name from a root"),
    ]

    name: str
    "A template name looked up in the roots, or a file path when no --root is given"
    ("name",)

    data: _ty.Optional[str] = None
    "A JSON file holding an object of top-level names, or - for standard input"
    ("--data", "-d")

    assignments: _ty.List[str] = []
    "A key=value name, over --data; a.b=v nests, v of json:... is JSON; repeat for more"
    ("--set", "-s")

    output: str = "-"
    "Where the result goes: a file path, or - for standard output"
    ("--output", "-o")

    def __call__(self) -> int:
        lookup, name = self.resolve(self.name)
        rendered = lookup.render(name, self.values())
        self.write(rendered)
        return 0

    def values(self) -> "_ty.Dict[str, _ty.Any]":
        """The data: `--data`, then each `--set` over it."""
        values: _ty.Dict[str, _ty.Any] = {}
        if self.data is not None:
            values.update(self.read_data())
        return merge(values, parse_assignments(self.assignments))

    def read_data(self) -> "_ty.Dict[str, _ty.Any]":
        try:
            if self.data == "-":
                loaded = json.load(sys.stdin)
            else:
                with open(self.data, encoding="utf-8") as handle:
                    loaded = json.load(handle)
        except ValueError as exc:
            raise UsageError(f"--data {self.data}: not JSON: {exc}") from exc
        if not isinstance(loaded, dict):
            raise UsageError(f"--data {self.data}: must hold a JSON object")
        return loaded

    def write(self, rendered: "_ty.Union[str, bytes]") -> None:
        """Bytes are written as they are; text as UTF-8 with its newlines unchanged."""
        data = rendered if isinstance(rendered, bytes) else rendered.encode("utf-8")
        if self.output == "-":
            sys.stdout.flush()
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        else:
            with open(self.output, "wb") as handle:
                handle.write(data)
