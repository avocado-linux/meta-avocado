"""Hygiene gate for the remote-medium tree.

Fails when: a test password leaks into a record, log or production source;
a forbidden token appears anywhere in the tree (matched by sha256 only, so
the tokens never appear here); a runner-side module imports outside the
standard library; or a plan/check/status module can reach a mutating verb.
"""

import ast
import hashlib
import os
import pathlib
import re
import sys

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[2]
PKG = SCRIPTS / "avocado_flash_remote"
TESTS = SCRIPTS / "tests" / "remote"
GOLDEN = TESTS / "golden"
LAUNCHER = SCRIPTS / "avocado-flash"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# sha256 of lowercased forbidden tokens. A token is matched as any 4..12 char
# window of a single word, or of two adjacent words joined (words are
# [A-Za-z0-9]+ runs, so a hyphenated token is its two words joined).
FORBIDDEN_SHA256 = {
    "d6dd264953077dd8850aafdb94088f1708895142b17fcd3574627fe27ec43188",
    "3918b30593b4c946363930263b52b5b9018336f85f56a09875e29b4b05046313",
    "b4a765079f318f788b798732cca02d3d6445bb3fa30f0466c2a7cb84a512e100",
}
WORD = re.compile(r"[A-Za-z0-9]+")
WINDOWS = range(4, 13)
SECRET_NAME = re.compile(r"password|passwd|secret", re.I)
OS_MUTATORS = {"remove", "rename", "unlink", "system", "popen", "write", "mkdir", "makedirs"}


def scanned_files(root_pkg=PKG, root_tests=TESTS, launcher=LAUNCHER):
    out = []
    for base in (root_pkg, root_tests):
        for p in sorted(pathlib.Path(base).rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                out.append(p)
    if pathlib.Path(launcher).is_file():
        out.append(pathlib.Path(launcher))
    return out


def read_text(path):
    data = pathlib.Path(path).read_bytes()
    if b"\0" in data:
        return None
    return data.decode("utf-8", errors="replace")


def _hashes(s):
    for n in WINDOWS:
        for i in range(len(s) - n + 1):
            yield hashlib.sha256(s[i : i + n].encode()).hexdigest()


def forbidden_hits(text, forbidden=FORBIDDEN_SHA256):
    words = [w.lower() for w in WORD.findall(text)]
    cands = set(words)
    cands.update(a + b for a, b in zip(words, words[1:]))
    for c in cands:
        for h in _hashes(c):
            if h in forbidden:
                return True
    return False


def scan_forbidden(files, forbidden=FORBIDDEN_SHA256):
    hits = []
    for p in files:
        text = read_text(p)
        if text is not None and forbidden_hits(text, forbidden):
            hits.append(str(p))
    return hits


def collect_secrets(tests_dir=TESTS):
    """String literals assigned to password/passwd/secret-named targets."""
    found = set()
    for p in sorted(pathlib.Path(tests_dir).glob("*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                continue
            for t in targets:
                name = t.id if isinstance(t, ast.Name) else t.attr if isinstance(t, ast.Attribute) else ""
                if SECRET_NAME.search(name) and len(value.value) >= 6:
                    found.add(value.value)
    return found


def scan_for_secrets(root, secrets, golden=None):
    """Files under ``root`` that contain any secret.

    Scans every golden file, every json/log/txt file, and every package
    module (anything but test_*.py).
    """
    root = pathlib.Path(root)
    golden = pathlib.Path(golden) if golden else root / "golden"
    leaks = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts or p.name.startswith("test_") and p.suffix == ".py":
            continue
        in_golden = golden in p.parents
        if not (in_golden or p.suffix in (".json", ".log", ".txt") or p.suffix == ".py"):
            continue
        text = read_text(p)
        if text is None:
            continue
        for s in secrets:
            if s in text:
                leaks.append((str(p), "secret literal"))
                break
    return leaks


def foreign_imports(source, package="avocado_flash_remote"):
    stdlib = sys.stdlib_module_names
    bad = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            names = [(node.module or "").split(".")[0]]
        else:
            continue
        bad += [n for n in names if n and n != package and n not in stdlib]
    return bad


def mutating_verbs(ops_path=PKG / "ops.py"):
    """Ops methods whose body gates on a mutating verb (``_gate(name, True)``)."""
    tree = ast.parse(pathlib.Path(ops_path).read_text())
    verbs = set()
    for cls in (n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Ops"):
        for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef)):
            for c in ast.walk(fn):
                if (
                    isinstance(c, ast.Call)
                    and isinstance(c.func, ast.Attribute)
                    and c.func.attr == "_gate"
                    and len(c.args) == 2
                    and isinstance(c.args[1], ast.Constant)
                    and c.args[1].value is True
                    and fn.name != "run_read"
                ):
                    verbs.add(fn.name)
    return verbs


def readonly_violations(source, verbs):
    out = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr in verbs:
            out.append(f"line {node.lineno}: attribute {node.attr}")
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] in ("subprocess", "shutil"):
                    out.append(f"line {node.lineno}: import {a.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in ("subprocess", "shutil"):
                out.append(f"line {node.lineno}: import from {node.module}")
            if node.module == "os" and any(a.name in OS_MUTATORS for a in node.names):
                out.append(f"line {node.lineno}: from os import mutator")
        if (
            isinstance(node, ast.Attribute)
            and node.attr in OS_MUTATORS
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        ):
            out.append(f"line {node.lineno}: os.{node.attr}")
    return out


# ------------------------------------------------------------ real tree


def test_no_forbidden_tokens_in_tree():
    files = scanned_files()
    assert len(files) > 20
    assert scan_forbidden(files) == []


def test_gate_covers_itself():
    assert str(pathlib.Path(__file__).resolve()) in {str(p) for p in scanned_files()}


def test_no_test_password_leaks():
    secrets = collect_secrets()
    assert secrets, "no test password literal found; the gate would pass vacuously"
    assert scan_for_secrets(TESTS, secrets) == []
    assert scan_for_secrets(PKG, secrets) == []
    assert not any(s in LAUNCHER.read_text(errors="replace") for s in secrets)


def test_runner_modules_are_stdlib_only():
    from avocado_flash_remote.bundle import ARCHIVE_MODULES

    assert len(ARCHIVE_MODULES) >= 10
    for mod in ARCHIVE_MODULES:
        src = (PKG / f"{mod}.py").read_text()
        assert foreign_imports(src) == [], mod


def test_mutating_verb_list_is_not_vacuous():
    verbs = mutating_verbs()
    assert len(verbs) >= 10
    assert {"dd_write", "sfdisk_write", "efibootmgr_create"} <= verbs


@pytest.mark.parametrize("mod", ["cmd_plan", "cmd_check", "cmd_status"])
def test_read_only_modules_do_not_mutate(mod):
    assert readonly_violations((PKG / f"{mod}.py").read_text(), mutating_verbs()) == []


def test_no_home_paths_leak():
    user = os.path.basename(os.path.expanduser("~"))
    for p in scanned_files():
        if p == pathlib.Path(__file__).resolve():
            continue
        text = read_text(p)
        if text is None:
            continue
        if p == LAUNCHER or PKG in p.parents:
            assert "/home/" not in text, p
            assert user.lower() not in text.lower() or len(user) < 4, p


# ------------------------------------------------------- negative tests


def _tok(codes):
    return "".join(chr(c) for c in codes)


def test_negative_forbidden_token_flagged(tmp_path):
    word = _tok([98, 111, 112, 97])  # a forbidden token, built at runtime
    (tmp_path / "a.txt").write_text(f"x {word}-rest\n")
    (tmp_path / "b.txt").write_text(f"embedded x{word}x\n")
    (tmp_path / "ok.txt").write_text("nothing here\n")
    hits = scan_forbidden(sorted(tmp_path.iterdir()))
    assert sorted(pathlib.Path(h).name for h in hits) == ["a.txt", "b.txt"]


def test_negative_adjacent_pair_flagged(tmp_path):
    pair = _tok([97, 110, 116]) + "-" + _tok([104, 101, 97, 108, 116, 104])
    (tmp_path / "a.txt").write_text(f"see {pair} docs\n")
    assert scan_forbidden([tmp_path / "a.txt"])


def test_negative_leaked_password_flagged(tmp_path):
    (tmp_path / "golden").mkdir()
    (tmp_path / "golden" / "rec.txt").write_text("line pw-literal-123 here\n")
    (tmp_path / "mod.py").write_text("X = 'pw-literal-123'\n")
    (tmp_path / "test_x.py").write_text("PASSWORD = 'pw-literal-123'\n")
    assert collect_secrets(tmp_path) == {"pw-literal-123"}
    leaks = scan_for_secrets(tmp_path, {"pw-literal-123"})
    assert sorted(pathlib.Path(p).name for p, _ in leaks) == ["mod.py", "rec.txt"]


def test_negative_bad_import_flagged():
    assert foreign_imports("import os\nimport requests\n") == ["requests"]
    assert foreign_imports("from yaml import safe_load\n") == ["yaml"]
    assert foreign_imports("import os, json\nfrom . import x\n") == []


def test_negative_plan_calling_mutator_flagged():
    verbs = mutating_verbs()
    assert readonly_violations("def f(ops):\n    ops.dd_write('a', 'b')\n", verbs)
    assert readonly_violations("import subprocess\n", verbs)
    assert readonly_violations("import os\nos.remove('x')\n", verbs)
    assert readonly_violations("def f(ops):\n    return ops.lsblk('x')\n", verbs) == []
