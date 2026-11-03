"""The provisioning script's cpp wrapper, run from its real text.

A hardware run hung 57 minutes in "Signing binaries": with no SDK on PATH the
script's fallback writes a ``cpp`` wrapper that execs ``cpp``, which resolves
to the wrapper itself. The tool stages ``<machine>-avocadosdk-linux-cpp`` so
the script's first branch wins. These tests execute the block the script
really contains, so a change to the script text is tested, not assumed.
"""

import os
import platform
import shutil
import signal
import subprocess
from types import SimpleNamespace

import pytest

from avocado_flash_tegra import flow

pytestmark = pytest.mark.real_subprocess

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "meta-avocado-nvidia" / "stone" / "tegra" / "stone-provision-tegraflash.sh"
START = "temp_bin_dir=$(mktemp -d)"
END = 'export PATH="$temp_bin_dir:$build_dir:$PATH"'

BASH = shutil.which("bash")
HOST_CPP = shutil.which("cpp")


def extract_block(text: str) -> str:
    """The script lines from the temp dir creation through the PATH export."""
    lines = text.splitlines()
    first = [i for i, line in enumerate(lines) if line.strip() == START]
    last = [i for i, line in enumerate(lines) if line.strip() == END]
    assert len(first) == 1, f"expected one {START!r} line, found {len(first)}"
    assert len(last) == 1, f"expected one {END!r} line, found {len(last)}"
    assert first[0] < last[0]
    return "\n".join(lines[first[0] : last[0] + 1]) + "\n"


def run_group(argv, *, env, stdin=None, timeout=10):
    """Run argv in its own session; on timeout kill only that group."""
    proc = subprocess.Popen(
        argv,
        env=env,
        stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        pytest.fail(f"{argv} did not finish within {timeout}s")
    return proc.returncode, out, err


def generate_wrapper(bin_dir, build_dir, block):
    """Run the real block; return (wrapper path, wrapper text)."""
    driver = (
        "set -e\n" + block + 'printf "%s\\n" "$temp_bin_dir/cpp"\n'
        'cat "$temp_bin_dir/cpp" >&2\n'
    )
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "build_dir": str(build_dir)}
    # The script's EXIT trap deletes the wrapper dir, so copy the file out
    # before the shell exits: re-run with the trap replaced by a copy.
    driver = driver.replace(
        "trap 'rm -rf \"$temp_bin_dir\"' EXIT",
        'trap \'cp "$temp_bin_dir/cpp" "$build_dir/wrapper-copy"; rm -rf "$temp_bin_dir"\' EXIT',
    )
    rc, out, err = run_group([BASH, "-c", driver], env=env)
    assert rc == 0, err
    return build_dir / "wrapper-copy"


def stage(tmp_path, with_alias):
    ctx = SimpleNamespace(
        workdir=SimpleNamespace(path=tmp_path / "work"),
        helper_source=tmp_path / "helper-src",
    )
    ctx.workdir.path.mkdir(mode=0o700)
    ctx.helper_source.write_text("#!/bin/sh\n")
    bin_dir = flow._stage_helper(ctx)
    if not with_alias:
        os.unlink(bin_dir / flow._cpp_alias_name())
    return bin_dir


needs_tools = pytest.mark.skipif(
    BASH is None or HOST_CPP is None,
    reason="needs bash and a host cpp on PATH",
)


def test_extraction_fails_loudly_on_a_script_without_the_block():
    with pytest.raises(AssertionError):
        extract_block("echo nothing here\n")


@needs_tools
def test_staged_alias_makes_the_wrapper_exec_the_alias_and_preprocess(tmp_path):
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    bin_dir = stage(tmp_path, with_alias=True)
    block = extract_block(SCRIPT.read_text())
    copy = generate_wrapper(bin_dir, build_dir, block)
    alias = f"{platform.machine()}-avocadosdk-linux-cpp"
    assert f'exec {alias} "$@"' in copy.read_text().splitlines()

    env = {"PATH": f"{bin_dir}:/usr/bin:/bin"}
    rc, out, err = run_group(
        [str(copy), "-E", "-P", "-x", "c", "-"],
        env=env,
        stdin="#define A 1\nA\n",
    )
    assert rc == 0, err
    assert "1" in out


@needs_tools
def test_without_the_alias_the_wrapper_is_the_self_referencing_loop(tmp_path):
    # Read only: this wrapper execs itself forever and must never be run.
    build_dir = tmp_path / "build"
    build_dir.mkdir()
    bin_dir = stage(tmp_path, with_alias=False)
    # Hide any real nativesdk cpp the host might carry by pinning PATH to the
    # staged dir plus the system dirs, as generate_wrapper does.
    block = extract_block(SCRIPT.read_text())
    copy = generate_wrapper(bin_dir, build_dir, block)
    assert 'exec cpp "$@"' in copy.read_text().splitlines()
