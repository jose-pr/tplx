"""The `tplx` command line, through its real parser."""

import json
import subprocess
import sys

import pytest

pytest.importorskip("duho", reason="needs the 'cli' extra")
pytest.importorskip("jinja2", reason="needs the 'jinja' extra")

from tplx.cli import main  # noqa: E402


@pytest.fixture
def project(tree, monkeypatch):
    tree.write("boot.cfg.j2", "host={{ target.hostname }} ip={{ target.ip }}\n")
    tree.write("net.shtpl", "IP=%{TARGET_IP}\n")
    monkeypatch.chdir(tree.root.parent)
    return tree


def test_render_a_name_with_data_and_set(project, capsys):
    (project.root.parent / "host.json").write_text('{"target": {"ip": "10.0.0.5"}}')
    status = main(
        ["render", "boot.cfg", "-d", "host.json", "-s", "target.hostname=web01"]
    )
    assert status == 0
    assert capsys.readouterr().out == "host=web01 ip=10.0.0.5\n"


def test_render_a_file_path_uses_its_directory_as_the_root(project, capsys):
    assert main(["render", "templates/net.shtpl", "-s", "target.ip=1.2.3.4"]) == 0
    assert capsys.readouterr().out == "IP=1.2.3.4\n"


def test_set_takes_json_values(project, capsys):
    project.write("n.j2", "{{ n + 1 }} {{ xs | join(',') }}")
    assert main(["render", "n", "-s", "n=json:2", "-s", 'xs=json:["a","b"]']) == 0
    assert capsys.readouterr().out == "3 a,b"


def test_render_to_a_file_keeps_bytes(project):
    project.write("blob.bin", b"\x00\xff\r\n")
    out = project.root.parent / "out.bin"
    assert main(["render", "blob.bin", "-o", str(out)]) == 0
    assert out.read_bytes() == b"\x00\xff\r\n"


def test_data_from_standard_input(project, monkeypatch, capsys):
    import io

    payload = json.dumps({"target": {"hostname": "h", "ip": "i"}})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    assert main(["render", "boot.cfg", "-d", "-"]) == 0
    assert capsys.readouterr().out == "host=h ip=i\n"


def test_undefined_mode_and_failures(project, capsys):
    assert main(["render", "boot.cfg"]) == 1
    assert "undefined" in capsys.readouterr().err
    capsys.readouterr()
    assert main(["render", "net", "-u", "lenient"]) == 0
    assert capsys.readouterr().out == "IP=\n"
    assert main(["render", "nope"]) == 1
    assert "not found" in capsys.readouterr().err


def test_a_bad_set_is_a_usage_error(project, capsys):
    assert main(["render", "boot.cfg", "-s", "nokey"]) == 2
    assert "key=value" in capsys.readouterr().err


def test_find_names_the_file_and_engine(project, capsys):
    assert main(["find", "boot.cfg"]) == 0
    origin, engine = capsys.readouterr().out.strip().split("\t")
    assert origin.endswith("boot.cfg.j2") and engine == "JinjaTemplate"
    assert main(["which", "net", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["engine"] == "ShellTemplate"


def test_paths_are_searched_before_the_roots(project, capsys):
    project.write("debian/net.shtpl", "debian\n")
    assert main(["render", "net", "-p", "debian"]) == 0
    assert capsys.readouterr().out == "debian\n"


def test_engines_lists_the_registry(capsys):
    assert main(["engines", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["engine"] == "JinjaTemplate" and rows[-1]["suffixes"] == ["*"]


def test_python_dash_m_runs_the_same_program():
    result = subprocess.run(
        [sys.executable, "-m", "tplx", "--version"], capture_output=True, text=True
    )
    assert result.returncode == 0 and result.stdout.startswith("tplx ")


def test_without_the_extra_the_command_names_it(monkeypatch):
    monkeypatch.setitem(sys.modules, "duho", None)
    with pytest.raises(SystemExit, match=r"tplx\[cli\]"):
        main(["engines"])


def test_importing_tplx_does_not_import_the_command_line():
    code = "import sys, tplx; print('duho' in sys.modules, 'tplx.cli' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False False"
