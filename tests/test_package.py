from importlib.resources import files

import tplx


def test_version_comes_from_the_installed_metadata():
    assert tplx.__version__ != "0.0.0"


def test_the_package_ships_its_type_marker_and_api_header():
    root = files("tplx")
    assert (root / "py.typed").is_file()
    assert (root / "AGENTS.md").is_file()
