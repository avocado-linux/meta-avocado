import ast
import shutil
import sys
from pathlib import Path

import avocado_tegraflash

PACKAGE = "avocado_tegraflash"
PKG_DIR = Path(avocado_tegraflash.__file__).resolve().parent
NETWORK = {"socket", "ssl", "http", "urllib", "ftplib", "smtplib", "socketserver", "xmlrpc", "asyncio", "telnetlib", "imaplib", "poplib"}


def violations(pkg_dir: Path) -> list[str]:
    bad = []
    for src in sorted(pkg_dir.rglob("*.py")):
        tree = ast.parse(src.read_text(), filename=str(src))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                names = [node.module or ""]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top == PACKAGE:
                    continue
                if top in NETWORK or top not in sys.stdlib_module_names:
                    bad.append(f"{src.name}: {name}")
    return bad


def test_engine_imports_stdlib_only():
    assert violations(PKG_DIR) == []


def _mutated(tmp_path, line):
    copy = tmp_path / PACKAGE
    tmp_path.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PKG_DIR, copy, ignore=shutil.ignore_patterns("__pycache__"))
    with (copy / "cli.py").open("a") as fh:
        fh.write("\n" + line + "\n")
    return copy


def test_third_party_import_is_detected(tmp_path):
    assert violations(_mutated(tmp_path, "import requests")) == ["cli.py: requests"]


def test_network_import_is_detected(tmp_path):
    assert violations(_mutated(tmp_path / "a", "import socket")) == ["cli.py: socket"]
    assert violations(_mutated(tmp_path / "b", "from urllib.request import urlopen")) == ["cli.py: urllib.request"]
