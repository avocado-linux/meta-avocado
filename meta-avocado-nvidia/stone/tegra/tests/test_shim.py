"""The provisioning shim: checks, then hands over to the engine unchanged.

The shim is run for real through bash with a PATH built from symlinks, so a
missing or too-old python3 is a property of the PATH and not of a mock. The
engine is a stand-in package under a fake data directory.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from parity import runner

SHIM = Path(__file__).resolve().parent.parent / "stone-provision-tegraflash.sh"
FORBIDDEN = ("jq", "sed", "cp", "fdtget", "fdtput", "lsusb", "initrd-flash", "boardctl")

ENGINE_MAIN = '''\
import json
import os
import sys

from . import sibling

with open(os.environ["ENGINE_LOG"], "w") as handle:
    json.dump(
        {
            "argv": sys.argv[1:],
            "marker": os.environ.get("MARKER"),
            "path": os.environ.get("PATH"),
            "data_dir": os.environ.get("AVOCADO_STONE_DATA_DIR"),
            "file": __file__,
            "sibling": sibling.VALUE,
        },
        handle,
    )
sys.exit(int(os.environ.get("ENGINE_EXIT", "0")))
'''

ENGINE_INIT = '''\
import colorsys  # a stdlib module a PYTHONPATH decoy can shadow

COLORSYS_FILE = colorsys.__file__
'''

OLD_PYTHON = """\
#!{exe}
import sys

sys.version_info = (3, 9, 18, "final", 0)
args = sys.argv[2:] if sys.argv[1:2] == ["-I"] else sys.argv[1:]
if len(args) > 1 and args[0] == "-c":
    code = args[1]
    sys.argv = ["-c"] + args[2:]
    exec(compile(code, "<string>", "exec"))
else:
    sys.exit(99)
"""


def _run(shim, env, args=(), timeout=30):
    out = env["ENGINE_LOG"] + ".out"
    try:
        with open(out, "w") as sink:
            status = runner.run_in_own_session(
                [str(shim), *args], env=env, stdin=subprocess.DEVNULL, stdout=sink, timeout=timeout
            )
    except subprocess.TimeoutExpired:
        pytest.fail("the shim did not finish in time")
    return status, Path(out).read_text()


def _tool_dir(root, *, python=True):
    """A PATH holding only what the shebang line needs, plus python3 when asked."""
    bin_dir = root / "pathbin"
    bin_dir.mkdir(exist_ok=True)
    for name in ("env", "bash"):
        link = bin_dir / name
        if not link.exists():
            link.symlink_to(_which(name))
    link = bin_dir / "python3"
    if python and not link.exists():
        link.symlink_to(os.path.realpath(sys.executable))
    return bin_dir


def _which(name):
    for directory in ("/usr/bin", "/bin"):
        candidate = Path(directory) / name
        if candidate.exists():
            return candidate
    raise RuntimeError(f"{name} not found in /usr/bin or /bin")


def _engine(data_dir):
    package = data_dir / "tegraflash-engine" / "avocado_tegraflash"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(ENGINE_INIT)
    (package / "sibling.py").write_text('VALUE = "sibling"\n')
    (package / "__main__.py").write_text(ENGINE_MAIN)


@pytest.fixture
def rig(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _engine(data_dir)
    env = {
        "PATH": str(_tool_dir(tmp_path)),
        "HOME": str(tmp_path),
        "AVOCADO_STONE_DATA_DIR": str(data_dir),
        "ENGINE_LOG": str(tmp_path / "engine.json"),
        "MARKER": "visible",
    }
    return tmp_path, data_dir, env


def _seen(env):
    return json.loads(Path(env["ENGINE_LOG"]).read_text())


def _ran(env):
    return Path(env["ENGINE_LOG"]).exists()


def _mutant(tmp_path, old, new):
    text = SHIM.read_text()
    assert text.count(old) == 1, f"{old!r} found {text.count(old)} times"
    copy = tmp_path / "mutant.sh"
    copy.write_text(text.replace(old, new))
    copy.chmod(0o755)
    return copy


def test_missing_engine_directory_names_the_looked_in_path_and_never_runs(rig):
    tmp_path, data_dir, env = rig
    env["AVOCADO_STONE_DATA_DIR"] = str(tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    rc, out = _run(SHIM, env)
    assert (rc != 0, str(tmp_path / "empty" / "tegraflash-engine") in out, _ran(env)) == (True, True, False)


def test_engine_directory_without_the_package_main_is_refused(rig):
    _, data_dir, env = rig
    (data_dir / "tegraflash-engine" / "avocado_tegraflash" / "__main__.py").unlink()
    rc, out = _run(SHIM, env)
    assert (rc != 0, _ran(env)) == (True, False)


def test_unset_data_directory_variable_is_refused_naming_it(rig):
    _, _, env = rig
    del env["AVOCADO_STONE_DATA_DIR"]
    rc, out = _run(SHIM, env)
    assert (rc, "AVOCADO_STONE_DATA_DIR" in out, _ran(env)) == (1, True, False)


def test_empty_data_directory_variable_is_refused_without_looking_for_the_engine(rig):
    _, _, env = rig
    env["AVOCADO_STONE_DATA_DIR"] = ""
    rc, out = _run(SHIM, env)
    assert (rc, "AVOCADO_STONE_DATA_DIR" in out, "looked in" in out) == (1, True, False)


def test_absent_python3_names_python3_and_never_exits_zero(rig):
    tmp_path, _, env = rig
    (tmp_path / "pathbin" / "python3").unlink()
    rc, out = _run(SHIM, env)
    assert (rc, "python3" in out, _ran(env)) == (1, True, False)


def test_python3_below_3_10_names_the_found_version_and_3_10(rig):
    tmp_path, _, env = rig
    old = tmp_path / "oldbin"
    old.mkdir()
    fake = old / "python3"
    fake.write_text(OLD_PYTHON.format(exe=os.path.realpath(sys.executable)))
    fake.chmod(0o755)
    env["PATH"] = f"{old}:{env['PATH']}"
    rc, out = _run(SHIM, env)
    assert (rc, "3.9" in out, "3.10" in out, _ran(env)) == (1, True, True, False)


def test_arguments_reach_the_engine_after_argv0_in_order(rig):
    _, _, env = rig
    rc, out = _run(SHIM, env, ("--prepare-only", "second arg", ""))
    assert (rc, _seen(env)["argv"]) == (0, ["--prepare-only", "second arg", ""])


def test_no_arguments_reach_the_engine_as_an_empty_list(rig):
    _, _, env = rig
    _run(SHIM, env)
    assert _seen(env)["argv"] == []


def test_environment_reaches_the_engine_untouched(rig):
    _, data_dir, env = rig
    _run(SHIM, env)
    seen = _seen(env)
    assert (seen["marker"], seen["path"], seen["data_dir"]) == ("visible", env["PATH"], str(data_dir))


@pytest.mark.parametrize("status", [0, 7])
def test_engine_exit_status_is_the_shim_exit_status(rig, status):
    _, _, env = rig
    env["ENGINE_EXIT"] = str(status)
    rc, out = _run(SHIM, env)
    assert rc == status


def test_the_engine_directory_is_the_import_root_of_the_stand_in(rig):
    _, data_dir, env = rig
    _run(SHIM, env)
    expected = data_dir / "tegraflash-engine" / "avocado_tegraflash" / "__main__.py"
    assert (_seen(env)["file"], _seen(env)["sibling"]) == (str(expected), "sibling")


def _decoys(tmp_path):
    decoy = tmp_path / "decoy"
    package = decoy / "avocado_tegraflash"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        f'open({str(tmp_path / "package-decoy-imported")!r}, "w").close()\n'
    )
    (decoy / "colorsys.py").write_text(
        f'open({str(tmp_path / "stdlib-decoy-imported")!r}, "w").close()\n'
    )
    return decoy


def test_pythonpath_package_named_like_the_engine_is_not_imported(rig):
    tmp_path, _, env = rig
    env["PYTHONPATH"] = str(_decoys(tmp_path))
    rc, out = _run(SHIM, env)
    assert (rc, (tmp_path / "package-decoy-imported").exists(), _ran(env)) == (0, False, True)


def test_pythonpath_module_shadowing_the_stdlib_is_not_imported(rig):
    tmp_path, _, env = rig
    env["PYTHONPATH"] = str(_decoys(tmp_path))
    _run(SHIM, env)
    assert not (tmp_path / "stdlib-decoy-imported").exists()


def _stray_json(data_dir, tmp_path):
    (data_dir / "tegraflash-engine" / "json.py").write_text(
        f'open({str(tmp_path / "stray-json-imported")!r}, "w").close()\n'
    )


def test_a_stray_stdlib_named_module_in_the_engine_directory_is_not_imported(rig):
    tmp_path, data_dir, env = rig
    _stray_json(data_dir, tmp_path)
    rc, _ = _run(SHIM, env)
    assert (rc, (tmp_path / "stray-json-imported").exists(), _ran(env)) == (0, False, True)


def test_mutant_putting_the_engine_directory_first_imports_the_stray_module(rig):
    tmp_path, data_dir, env = rig
    _stray_json(data_dir, tmp_path)
    mutant = _mutant(tmp_path, "sys.path.append(sys.argv[1])", "sys.path.insert(0, sys.argv[1])")
    _run(mutant, env)
    assert (tmp_path / "stray-json-imported").exists()


def _sitecustomize(tmp_path):
    site = tmp_path / "sitedir"
    site.mkdir()
    (site / "sitecustomize.py").write_text(
        f'open({str(tmp_path / "sitecustomize-ran")!r}, "w").close()\n'
    )
    return site


def test_sitecustomize_on_pythonpath_never_runs_before_the_engine(rig):
    tmp_path, _, env = rig
    env["PYTHONPATH"] = str(_sitecustomize(tmp_path))
    rc, out = _run(SHIM, env)
    assert (rc, (tmp_path / "sitecustomize-ran").exists(), _ran(env)) == (0, False, True)


def test_mutant_version_query_without_isolation_runs_sitecustomize(rig):
    tmp_path, _, env = rig
    mutant = _mutant(tmp_path, "python3 -I -c 'import sys; sys.exit(", "python3 -c 'import sys; sys.exit(")
    env["PYTHONPATH"] = str(_sitecustomize(tmp_path))
    _run(mutant, env)
    assert (tmp_path / "sitecustomize-ran").exists()


def test_no_bytecode_directory_is_left_under_the_data_directory(rig):
    _, data_dir, env = rig
    _run(SHIM, env)
    assert (_ran(env), list(data_dir.rglob("__pycache__"))) == (True, [])


def test_engine_directory_with_quote_space_and_semicolon_still_works(tmp_path):
    data_dir = tmp_path / "it's a ;dir"
    data_dir.mkdir()
    _engine(data_dir)
    env = {
        "PATH": str(_tool_dir(tmp_path)),
        "AVOCADO_STONE_DATA_DIR": str(data_dir),
        "ENGINE_LOG": str(tmp_path / "engine.json"),
    }
    rc, out = _run(SHIM, env, ("x",))
    expected = data_dir / "tegraflash-engine" / "avocado_tegraflash" / "__main__.py"
    assert (rc, _seen(env)["file"], _seen(env)["argv"]) == (0, str(expected), ["x"])


def test_shim_is_at_most_40_lines():
    assert len(SHIM.read_text().splitlines()) <= 40


@pytest.mark.parametrize("word", FORBIDDEN)
def test_shim_names_none_of_the_retired_tools(word):
    assert re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", SHIM.read_text()) is None


def test_shim_is_executable_and_starts_with_the_bash_shebang():
    assert (os.access(SHIM, os.X_OK), SHIM.read_text().splitlines()[0]) == (True, "#!/usr/bin/env bash")


def test_shim_enables_set_e_and_u_and_never_swallows_a_status():
    text = SHIM.read_text()
    assert ("set -eu" in text, "|| true" in text, "set +e" in text) == (True, False, False)


def test_mutant_that_swallows_the_engine_status_is_caught(rig):
    tmp_path, _, env = rig
    first = _mutant(tmp_path, "exec python3 -I -B -c", "python3 -I -B -c")
    text = first.read_text()
    tail = "' \"$engine_dir\" \"$@\"\n"
    assert text.count(tail) == 1
    first.write_text(text.replace(tail, tail.rstrip("\n") + " || true\n"))
    mutant = first
    env["ENGINE_EXIT"] = "7"
    rc, out = _run(mutant, env)
    assert rc == 0


def test_mutant_without_isolation_imports_the_pythonpath_module(rig):
    tmp_path, _, env = rig
    mutant = _mutant(tmp_path, "python3 -I -B -c", "python3 -B -c")
    env["PYTHONPATH"] = str(_decoys(tmp_path))
    _run(mutant, env)
    # The engine directory is searched last, so the decoy package wins the import.
    assert (tmp_path / "package-decoy-imported").exists()


def test_mutant_without_the_no_bytecode_flag_leaves_a_pycache(rig):
    tmp_path, data_dir, env = rig
    mutant = _mutant(tmp_path, "python3 -I -B -c", "python3 -I -c")
    _run(mutant, env)
    assert list(data_dir.rglob("__pycache__")) != []


def test_mutant_without_the_data_directory_check_looks_under_the_filesystem_root(rig):
    tmp_path, _, env = rig
    mutant = _mutant(tmp_path, '[ -z "${AVOCADO_STONE_DATA_DIR:-}" ]', "false")
    env["AVOCADO_STONE_DATA_DIR"] = ""
    rc, out = _run(mutant, env)
    assert (rc != 0, "AVOCADO_STONE_DATA_DIR" in out, "looked in" in out) == (True, False, True)
