"""No shell anywhere: hostile names stay data, and the source carries no shell-out."""

import ast
import json
import shutil
from pathlib import Path

import pytest

from avocado_tegraflash.cli import main
from avocado_tegraflash.runner import SubprocessRunner
from parity.cases import APX, STONE_DIR
from parity.fixtures import build_tree
from parity.stubs import write_stubs

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "avocado_tegraflash"
HOSTILE_IMAGE = "a;touch PWNED"
HOSTILE_TARGET = "x; touch PWNED"


def _stage(tmp_path):
    stub_dir = tmp_path / "stubs"
    log = tmp_path / "stub.log"
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps({"lsusb": [[], [APX]]}))
    write_stubs(stub_dir, log, scenario)
    doc = json.loads((STONE_DIR / "stone-jetson-orin-nano.json").read_text())
    doc["storage_devices"]["rootdisk"]["images"]["rootfs"] = HOSTILE_IMAGE
    manifest = tmp_path / "hostile-manifest.json"
    manifest.write_text(json.dumps(doc))
    tree = build_tree(manifest, tmp_path / "tree", stub_dir, kernel=True)
    environ = {
        "AVOCADO_STONE_MANIFEST": str(tree.manifest),
        "AVOCADO_STONE_BUILD_DIR": str(tree.build_dir),
        "AVOCADO_STONE_DATA_DIR": str(tree.data_dir),
        "AVOCADO_PROVISION_KERNEL_IMAGE": str(tree.kernel_image),
        "AVOCADO_SDK_ARCH": "x86_64",
        "BOARDCTL_TARGET": HOSTILE_TARGET,
        "PATH": f"{stub_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
    }
    return tree, environ, log


@pytest.fixture
def hostile_run(tmp_path, capsys):
    tree, environ, log = _stage(tmp_path)
    rc = main([], environ=environ, runner=SubprocessRunner(), euid=0, sleep=lambda _s: None)
    capsys.readouterr()
    records = [json.loads(line) for line in log.read_text().splitlines()]
    return rc, tree.build_dir / "tegraflash", records


@pytest.mark.real_subprocess
def test_hostile_names_run_end_to_end_with_the_real_runner_and_exit_0(hostile_run):
    rc, _, _ = hostile_run
    assert rc == 0


@pytest.mark.real_subprocess
def test_image_named_with_shell_text_is_copied_under_exactly_that_name(hostile_run):
    _, work, _ = hostile_run
    assert (work / HOSTILE_IMAGE).is_file()


@pytest.mark.real_subprocess
def test_boardctl_gets_the_hostile_target_as_one_argument(hostile_run):
    _, _, records = hostile_run
    boardctl = [r["argv"] for r in records if r["tool"] == "boardctl"]
    assert boardctl == [["-t", HOSTILE_TARGET, "recovery"]]


@pytest.mark.real_subprocess
def test_no_file_named_pwned_is_created_anywhere(tmp_path, hostile_run):
    stray = [p for p in tmp_path.rglob("PWNED")] + [p for p in Path.cwd().glob("PWNED")]
    assert stray == []


# --- source scan ---


def scan(source: str, name: str = "<source>") -> list:
    """Findings for shell-outs and dynamic evaluation in one module's source."""
    found = []
    for node in ast.walk(ast.parse(source, filename=name)):
        where = f"{name}:{getattr(node, 'lineno', 0)}"
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
                found.append(f"{where} {node.func.id}(")
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    found.append(f"{where} shell=True")
        elif isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "os" and node.attr in ("system", "popen"):
                found.append(f"{where} os.{node.attr}")
        elif isinstance(node, ast.ImportFrom) and node.module == "os":
            found.extend(f"{where} from os import {a.name}" for a in node.names if a.name in ("system", "popen"))
    return found


def scan_package(package_dir: Path) -> list:
    files = sorted(package_dir.glob("*.py"))
    assert files, f"no sources under {package_dir}"
    return [hit for f in files for hit in scan(f.read_text(), f.name)]


def test_package_sources_carry_no_shell_out_or_dynamic_evaluation():
    assert scan_package(PACKAGE_DIR) == []


@pytest.mark.parametrize(
    "snippet, expected",
    [
        ("import subprocess\nsubprocess.run('ls', shell=True)\n", "shell=True"),
        ("import os\nos.system('ls')\n", "os.system"),
        ("import os\nos.popen('ls')\n", "os.popen"),
        ("eval('1')\n", "eval("),
        ("exec('x = 1')\n", "exec("),
        ("from os import system\n", "from os import system"),
    ],
)
def test_scan_flags_each_forbidden_construct(snippet, expected):
    assert [hit.split(" ", 1)[1] for hit in scan(snippet)] == [expected]


def test_scan_ignores_shell_false_and_unrelated_names():
    assert scan("import subprocess\nsubprocess.run(['ls'], shell=False)\nevaluate = 1\n") == []


def test_package_scan_fails_on_a_mutated_copy(tmp_path):
    copy = tmp_path / "avocado_tegraflash"
    shutil.copytree(PACKAGE_DIR, copy, ignore=shutil.ignore_patterns("__pycache__"))
    cli = copy / "cli.py"
    cli.write_text(cli.read_text() + "\nimport os\nos.system('true')\n")
    assert [hit.split(" ", 1)[1] for hit in scan_package(copy)] == ["os.system"]
