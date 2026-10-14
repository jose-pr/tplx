import pytest

from tplx import _registry


@pytest.fixture(autouse=True)
def _restore_registry():
    """The registry is process-wide; put it back whatever a test does to it."""
    before = list(_registry._ENGINES)
    yield
    _registry._ENGINES[:] = before


class Tree:
    """A template root under a temporary directory."""

    def __init__(self, root):
        self.root = root

    def write(self, name: str, text, *, root=None):
        """Write a file as bytes, so line endings are what the test says."""
        path = (root or self.root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
        return path


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "templates"
    root.mkdir()
    return Tree(root)
