"""The suite every engine passes, shipped so a third-party engine runs it too.

Subclass `EngineContract` in a pytest test module, name the engine and a
source that writes the `name` value, and pytest collects the checks:

```python
from tplx.testing import EngineContract

class TestShoutyEngine(EngineContract):
    engine = ShoutyTemplate
    source = "{{ name }}"
    expected = "TPLX"
```

`expected` is what rendering `source` with `name="tplx"` returns. Every test
takes pytest's `tmp_path` fixture.
"""

from __future__ import annotations

from typing import Any, ClassVar, Optional, Union

from ._loader import Loader
from ._registry import FALLBACK_PRIORITY, template_extensions
from ._template import Template

__all__ = ["EngineContract"]


class EngineContract:
    """Checks one engine against the `Template` contract."""

    #: The engine class under test.
    engine: ClassVar[type]
    #: A template that writes the value of `name`.
    source: ClassVar[Union[str, bytes]]
    #: What `source` renders to with `name="tplx"`.
    expected: ClassVar[Union[str, bytes]]
    #: A file name the engine claims; the first suffix of `EXT` by default.
    filename: ClassVar[Optional[str]] = None

    def _filename(self) -> str:
        if self.filename:
            return self.filename
        suffixes = template_extensions(self.engine)
        return "contract" + (suffixes[0] if suffixes else ".contract")

    def _write(self, tmp_path: Any) -> Loader:
        source = self.source
        data = source if isinstance(source, bytes) else source.encode("utf-8")
        (tmp_path / self._filename()).write_bytes(data)
        return Loader([tmp_path], engines=[self.engine])

    def test_is_a_template(self) -> None:
        assert issubclass(self.engine, Template)

    def test_claims_its_own_file(self) -> None:
        assert self.engine.can_process(self._filename(), self.source)

    def test_renders_through_a_loader(self, tmp_path: Any) -> None:
        loader = self._write(tmp_path)
        assert loader.render(self._filename(), {"name": "tplx"}) == self.expected

    def test_a_keyword_overrides_the_data(self, tmp_path: Any) -> None:
        loader = self._write(tmp_path)
        rendered = loader.render(self._filename(), {"name": "other"}, name="tplx")
        assert rendered == self.expected

    def test_renders_without_a_loader(self) -> None:
        template = self.engine(self.source)
        assert template.render(name="tplx") == self.expected

    def test_returns_bytes_exactly_when_binary(self, tmp_path: Any) -> None:
        rendered = self._write(tmp_path).render(self._filename(), name="tplx")
        assert isinstance(rendered, bytes) is bool(self.engine.BINARY)

    def test_knows_its_origin(self, tmp_path: Any) -> None:
        template = self._write(tmp_path).get(self._filename())
        assert template.origin.endswith(self._filename())

    def test_a_suffix_engine_outranks_the_fallback(self) -> None:
        if template_extensions(self.engine) is not None:
            assert self.engine.PRIORITY > FALLBACK_PRIORITY
