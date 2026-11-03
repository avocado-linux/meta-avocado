"""Black-box tests: the real launcher as a subprocess, stub-only PATH.

Every external tool is a small shell stub that appends its name to a call
log, so a test can state exactly which tools ran. The PATH holds nothing but
those stubs plus links to the real env and sh.
"""

import os
import pathlib
import shutil
import subprocess
import sys

import pytest

LAUNCHER = pathlib.Path(__file__).resolve().parents[2] / "avocado-flash"

LISTING = "Bus 003 Device 005: ID 0955:7523 NVIDIA Corp. APX"

# Media lines that existed before the nvme medium; --help must keep them as is.
EXISTING_MEDIA_HELP = """\
media:
  sd        removable block device (SD card, USB stick); needs a device
  emmc      on-board eMMC over USB serial download
  ums       flash the board's own card in place. U-Boot exports it as USB mass
            storage, so the card never leaves the slot. Needs the board at a
            U-Boot prompt and a cable on the SoC's OTG port - on the FRDM-IMX93
            that is P2, not the power-only P1 or the debug P16.
  fuse-srk  program the AHAB SRK hash over the serial console. Never reachable
            from sd/emmc: flashing is repeatable, fuses are not.
  ssh-emmc  write a board's eMMC over SSH; must be the first argument and takes
            its own options (see 'avocado-flash ssh-emmc --help').
"""

FIRST_ARG_MESSAGE = "nvme must be the first argument: avocado-flash nvme [options]"


def _stub(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


@pytest.fixture
def stubs(tmp_path):
    bindir = tmp_path / "stubs"
    bindir.mkdir()
    calls = tmp_path / "calls.log"
    calls.write_text("")
    log = f'echo "${{0##*/}}" >> "{calls}"\n'
    _stub(bindir / "lsusb", log + f'echo "{LISTING}"\n')
    for name in ("jq", "fdtget", "fdtput", "cpp", "mkbootimg"):
        _stub(bindir / name, log)
    # `sudo -v` only refreshes the credential cache; the stub has none to ask for.
    _stub(bindir / "sudo", log + '[ "$1" = "-v" ] && exit 0\nexec "$@"\n')
    for name in ("env", "sh"):
        (bindir / name).symlink_to(shutil.which(name))
    return bindir, calls


def _record_script(tree, record):
    """Replace the fixture script with one that records where it can write.

    The invocation environment is built from scratch, so the fixture's
    $STUB_RECORD never reaches the script.
    """
    tree.script.write_text(
        "#!/bin/sh\n"
        "{\n"
        "  export -p\n"
        "  IFS=:; set -- $PATH; first=$1; IFS=\n"
        '  for f in "$first"/*; do [ -x "$f" ] && echo "HELPER $f"; done\n'
        f'}} >> "{record}"\n'
    )
    tree.script.chmod(0o755)


def run_launcher(stubs, tmp_path, args, stdin_text=None):
    bindir, _ = stubs
    env = {
        "PATH": str(bindir),
        "HOME": str(tmp_path),
        "AVOCADO_AGENT_SOCK": "/run/should-not-reach-the-script.sock",
    }
    return subprocess.run(
        [sys.executable, str(LAUNCHER), *args],
        env=env,
        stdin=subprocess.DEVNULL if stdin_text is None else None,
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=60,
    )


def nvme_args(tree, tmp_path, *extra):
    return [
        "nvme",
        "--deploy", str(tree.images_dir.parent.parent),
        "--workdir", str(tmp_path / "work"),
        *extra,
    ]


def tool_calls(calls):
    return calls.read_text().split()


pytestmark = pytest.mark.real_subprocess


def test_real_run_executes_script_with_five_variables(deploy_tree, stubs, tmp_path):
    record = tmp_path / "record.txt"
    _record_script(deploy_tree, record)

    proc = run_launcher(stubs, tmp_path, nvme_args(deploy_tree, tmp_path, "-y"))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    text = record.read_text()
    for var in (
        "AVOCADO_STONE_MANIFEST",
        "AVOCADO_STONE_DATA_DIR",
        "AVOCADO_STONE_BUILD_DIR",
        "AVOCADO_PROVISION_PROFILE",
        "AVOCADO_PROVISION_KERNEL_IMAGE",
    ):
        assert f"{var}=" in text
    assert "AVOCADO_PROVISION_PROFILE=\"tegraflash-nvme\"" in text
    assert "AVOCADO_AGENT_SOCK" not in text
    helpers = [ln for ln in text.splitlines() if ln.startswith("HELPER ")]
    work_bin = str(tmp_path / "work" / "bin")
    assert [h for h in helpers if h.startswith(f"HELPER {work_bin}/")], text


def _pinned_path(stubs, tmp_path, tree):
    proc = run_launcher(stubs, tmp_path, nvme_args(tree, tmp_path, "--dry-run"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("pinned: "))
    return line.split()[1]


def _without_sudo(calls):
    return [c for c in tool_calls(calls) if c != "sudo"]


def test_wrong_retype_aborts_before_the_script_runs(deploy_tree, stubs, tmp_path):
    _, calls = stubs
    record = tmp_path / "record.txt"
    _record_script(deploy_tree, record)
    calls.write_text("")

    proc = run_launcher(
        stubs, tmp_path, nvme_args(deploy_tree, tmp_path), stdin_text="not-the-device\n"
    )

    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "mismatch" in proc.stderr
    assert not record.exists()
    assert _without_sudo(calls) == ["lsusb"]


def test_correct_retype_runs_the_script(deploy_tree, stubs, tmp_path):
    _, calls = stubs
    record = tmp_path / "record.txt"
    _record_script(deploy_tree, record)
    pinned = _pinned_path(stubs, tmp_path, deploy_tree)
    calls.write_text("")

    proc = run_launcher(
        stubs, tmp_path, nvme_args(deploy_tree, tmp_path), stdin_text=pinned + "\n"
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "AVOCADO_PROVISION_PROFILE" in record.read_text()
    # One listing to pin, one to recheck after the confirmation.
    assert _without_sudo(calls) == ["lsusb", "lsusb"]


def test_closed_stdin_at_the_retype_is_refused_cleanly(deploy_tree, stubs, tmp_path):
    record = tmp_path / "record.txt"
    _record_script(deploy_tree, record)

    proc = run_launcher(stubs, tmp_path, nvme_args(deploy_tree, tmp_path))

    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "pass --assume-yes" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert not record.exists()


def test_dry_run_runs_only_lsusb(deploy_tree, stubs, tmp_path):
    _, calls = stubs

    proc = run_launcher(stubs, tmp_path, nvme_args(deploy_tree, tmp_path, "--dry-run"))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert tool_calls(calls) == ["lsusb"]
    assert "AVOCADO_PROVISION_PROFILE=tegraflash-nvme" in proc.stdout


def test_nvme_task_option_is_refused_before_the_usb_listing(deploy_tree, stubs, tmp_path):
    _, calls = stubs

    proc = run_launcher(stubs, tmp_path, nvme_args(deploy_tree, tmp_path, "--task", "upgrade"))

    assert proc.returncode == 2
    assert "avocado-flash nvme: error:" in proc.stderr
    assert tool_calls(calls) == []


@pytest.mark.parametrize(
    "argv",
    [
        ["sd", "--dry-run", "nvme"],
        ["--dry-run", "nvme"],
        ["sd", "nvme"],
    ],
)
def test_nvme_after_another_argument_is_refused(stubs, tmp_path, argv):
    _, calls = stubs

    proc = run_launcher(stubs, tmp_path, argv)

    assert proc.returncode == 1
    assert proc.stderr.strip() == f"avocado-flash: {FIRST_ARG_MESSAGE}"
    assert proc.stdout == ""
    assert tool_calls(calls) == []


def test_help_keeps_existing_media_lines_and_adds_nvme(stubs, tmp_path):
    proc = run_launcher(stubs, tmp_path, ["--help"])

    assert proc.returncode == 0
    assert EXISTING_MEDIA_HELP in proc.stdout
    assert "  nvme      " in proc.stdout
    assert "avocado-flash nvme --help" in proc.stdout
    assert "  avocado-flash nvme" in proc.stdout.split("examples:")[1]


def test_unknown_medium_keeps_usage_and_choices(stubs, tmp_path):
    proc = run_launcher(stubs, tmp_path, ["floppy"])

    assert proc.returncode == 2
    assert "{sd,emmc,ums,fuse-srk} [device]" in proc.stderr
    assert (
        "avocado-flash: error: argument medium: invalid choice: 'floppy' "
        "(choose from 'sd', 'emmc', 'ums', 'fuse-srk')"
    ) in proc.stderr
    assert "nvme" not in proc.stderr
