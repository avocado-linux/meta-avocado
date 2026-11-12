"""Every provision profile has exactly one proven run mode.

  1. declares dry_run: an executing test runs its script under recording stubs
     with AVOCADO_PROVISION_DRY_RUN=1 and sees no write. The mapped shell test
     (or the Jetson engine's pytest file) is EXECUTED here and must exit 0.
     Library scripts reach the write choke point, so one case per script covers
     every raw dd / fwup / uuu behind avocado_safe_disk_write.
  2. does not declare dry_run, but sources the library: its script refuses
     AVOCADO_PROVISION_DRY_RUN=1 before any write (avocado_safe_disk_modes with
     dry run not allowed); the mapped test executes that refusal.
  3. a classified non-writer.
  4. an exempt protocol writer that never reads the variable; the front-door
     assertions on it live in test_writer_coverage.

The fwup task has the same shape: a script applying an archive to a device
either honours AVOCADO_PROVISION_FWUP_TASK through avocado_safe_disk_fwup_task
or refuses a non-complete task through avocado_safe_disk_modes.

Deliberate debt: an exempt (class 4) script run directly through stone with
AVOCADO_PROVISION_DRY_RUN=1 is not tested; it ignores the variable and writes.
See the design risks.
"""

import os
import re
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from test_writer_coverage import (
    CLASSIFICATION,
    ROOT,
    _p,
    _read,
    code_lines,
    enumerate_entries,
    modes_call,
    sources_library,
)

TIMEOUT = 300

_NXP_TESTS = "meta-avocado-nxp/stone/avocado-imx/tests"
_DD_PROFILES = "meta-avocado-distro/stone/tests/test-dd-sd-profiles.sh"
_AMD_USB = (
    "meta-avocado-amd-x86-64/stone/amd-x86-64-v4/tests/test-stone-provision-usb.sh"
)
_RPI_USB = (
    "meta-avocado-raspberrypi/stone/rpi/tests/test-stone-provision-usb-safe-disk.sh"
)


def _sh(test, script=None):
    return ("bash", test) if script is None else ("bash", test, script)


# script -> argv (repo-relative) of the executing test that runs it under
# recording stubs with AVOCADO_PROVISION_DRY_RUN=1.
DRY_RUN_CASES = {
    _p("imx", "stone-provision-sd.sh"): _sh(
        f"{_NXP_TESTS}/test-stone-provision-sd-safe-disk.sh"
    ),
    _p("rpi", "stone-provision-sd.sh"): _sh(
        f"{_NXP_TESTS}/test-stone-provision-sd-safe-disk.sh",
        _p("rpi", "stone-provision-sd.sh"),
    ),
    _p("imx", "stone-provision-uuu-emmc.sh"): _sh(
        f"{_NXP_TESTS}/test-stone-provision-uuu-emmc.sh"
    ),
    _p("imx", "stone-provision-ums.sh"): _sh(
        f"{_NXP_TESTS}/test-stone-provision-ums.sh"
    ),
    _p("stm", "stone-provision-sd.sh"): _sh(
        "meta-avocado-stm/stone/stm32mp25-dk/tests/test-stone-provision-sd-safe-disk.sh"
    ),
    _p("nanopi", "stone-provision-ums.sh"): _sh(
        "meta-avocado-rockchip/stone/nanopi-r5s/tests/test-stone-provision-ums.sh"
    ),
    **{
        _p(k, "stone-provision-sd.sh"): _sh(
            _DD_PROFILES, _p(k, "stone-provision-sd.sh")
        )
        for k in ("alif", "rzv2n", "nanopi", "opi5")
    },
}

# The Jetson tegraflash profiles run through the Python engine, which has its
# own dry-run tests.
ENGINE_CASES = {
    _p("tegra", "stone-provision-tegraflash.sh"): (
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "meta-avocado-nvidia/stone/tegra/tests/test_dry_run_task.py",
    ),
}

# Scripts whose profile declares no dry_run: the test that executes the
# AVOCADO_PROVISION_DRY_RUN=1 refusal before any write.
REFUSAL_CASES = {
    **{
        _p(k, "stone-provision-usb.sh"): _sh(_AMD_USB, _p(k, "stone-provision-usb.sh"))
        for k in ("amd", "arm64", "i2", "i3", "i4")
    },
    _p("rpi", "stone-provision-usb.sh"): _sh(_RPI_USB),
}


def _test_file(argv):
    return next(a for a in argv if a.endswith((".sh", ".py")))


def run_mode_failures(
    entries, table, dry_cases, engine_cases, refusal_cases, read, exists
):
    """Failure strings for profiles lacking a proof of their run mode."""
    fails = []
    live = {e["script"] for e in entries}
    for name, cases in (
        ("dry-run", dry_cases),
        ("engine", engine_cases),
        ("refusal", refusal_cases),
    ):
        for script in cases:
            if script not in live:
                fails.append(f"stale {name} case: {script} matches no profile")
    for e in entries:
        who = f"{e['manifest']} profile {e['profile']} script {e['script']}"
        cls = table.get(e["script"])
        if cls is None:
            fails.append(f"unclassified: {who}")
            continue
        kind = cls[0]
        if kind in ("nonwriter", "exempt"):
            if e["dry_run"]:
                fails.append(
                    f"{kind} profile declares dry_run with nothing proving it: {who}"
                )
            continue
        if kind == "engine":
            cases = engine_cases
        elif e["dry_run"]:
            cases = dry_cases
        else:
            cases = refusal_cases
        argv = cases.get(e["script"])
        if argv is None:
            what = "dry-run" if e["dry_run"] else "dry-run refusal"
            fails.append(f"no executing {what} case: {who}")
            continue
        tf = _test_file(argv)
        if not exists(tf):
            fails.append(f"mapped test {tf} does not exist: {who}")
            continue
        text = read(tf) or ""
        if "DRY_RUN" not in text and "dry_run" not in text:
            fails.append(f"mapped test {tf} never mentions the dry run: {who}")
        # The tegraflash script is a shim; its engine tests call the engine directly.
        if (
            kind != "engine"
            and e["script"] not in argv
            and Path(e["script"]).name not in text
        ):
            fails.append(f"mapped test {tf} does not exercise {e['script']}: {who}")
    return fails


_FWUP_APPLY = re.compile(r"(?<![\w./-])fwup\s[^|;]*-a\b")
_CHOKE_FWUP = re.compile(r"avocado_safe_disk_write\s+fwup\b")
_TASK_VAR = re.compile(r"(\w+)=\$\(avocado_safe_disk_fwup_task\)")


def fwup_failures(texts):
    """texts: script path -> text. Every device-applying fwup must honour the task."""
    fails = []
    for script, text in texts.items():
        lines = code_lines(text)
        device_apply = [
            ln for ln in lines if _FWUP_APPLY.search(ln) and "archive_image" not in ln
        ]
        if not device_apply:
            continue
        modes = modes_call(text)
        if sources_library(text) and modes is not None:
            if modes[2] is False:
                # refuses a non-complete task before any write
                continue
            m = _TASK_VAR.search(text)
            if not m:
                fails.append(
                    f"{script}: applies fwup but never calls avocado_safe_disk_fwup_task"
                )
                continue
            for ln in device_apply:
                var = m.group(1)
                if f'-t "${var}"' not in ln and f'-t "${{{var}}}"' not in ln:
                    fails.append(
                        f"{script}: ignores FWUP_TASK, fwup line passes a fixed task: {ln}"
                    )
        else:
            fails.append(
                f"{script}: applies fwup to a device with neither the task nor a refusal"
            )
    return fails


def run_isolated(argv, tmp_path, label):
    """Run argv from the repo root in its own session; return (rc, output)."""
    out = tmp_path / f"{label}.out"
    with out.open("wb") as fh:
        proc = subprocess.Popen(
            list(argv),
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            rc = proc.wait(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            pgid = os.getpgid(proc.pid)
            if pgid == proc.pid and pgid > 1:
                os.killpg(pgid, signal.SIGTERM)
            proc.wait(timeout=30)
            rc = None
    return rc, out.read_text(errors="replace")


@pytest.fixture(scope="module")
def entries():
    return enumerate_entries()


def test_every_profile_has_a_proven_run_mode(entries):
    fails = run_mode_failures(
        entries,
        CLASSIFICATION,
        DRY_RUN_CASES,
        ENGINE_CASES,
        REFUSAL_CASES,
        _read,
        lambda p: (ROOT / p).is_file(),
    )
    assert not fails, "\n".join(fails)


def _unique_cases():
    seen, cases = set(), []
    for table in (DRY_RUN_CASES, ENGINE_CASES, REFUSAL_CASES):
        for script, argv in table.items():
            if argv not in seen:
                seen.add(argv)
                cases.append((script, argv))
    return cases


@pytest.mark.parametrize(
    "script,argv", _unique_cases(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_mapped_test_executes_green(script, argv, tmp_path):
    rc, out = run_isolated(argv, tmp_path, "case")
    assert rc == 0, f"{' '.join(argv)} (covers {script}) rc={rc}\n{out[-3000:]}"


def test_fwup_task_is_honoured_or_refused_by_every_fwup_script(entries):
    texts = {s: _read(s) for s in sorted({e["script"] for e in entries})}
    fails = fwup_failures(texts)
    assert not fails, "\n".join(fails)
    # The rule must actually see the fwup writers, not pass over an empty set.
    seen = [
        s
        for s, t in texts.items()
        if any(
            _FWUP_APPLY.search(ln) and "archive_image" not in ln for ln in code_lines(t)
        )
    ]
    assert _p("rpi", "stone-provision-usb.sh") in seen
    assert _p("imx", "stone-provision-sd.sh") in seen


# --- the checkers themselves, against synthetic inputs -------------------------

_E = {
    "manifest": "m/stone-b.json",
    "profile": "sd",
    "script": "x/a.sh",
    "dry_run": True,
}
_TBL = {"x/a.sh": ("library", ())}


def _rm(entry, table=_TBL, dry=None, eng=None, ref=None, tests=None):
    tests = (
        {"t/test.sh": "AVOCADO_PROVISION_DRY_RUN=1 a.sh"} if tests is None else tests
    )
    return run_mode_failures(
        [entry], table, dry or {}, eng or {}, ref or {}, tests.get, lambda p: p in tests
    )


def test_run_modes_flags_a_declaring_profile_with_no_executing_case():
    fails = _rm(_E)
    assert fails == [
        "no executing dry-run case: m/stone-b.json profile sd script x/a.sh"
    ]


def test_run_modes_passes_a_mapped_case():
    assert _rm(_E, dry={"x/a.sh": ("bash", "t/test.sh", "x/a.sh")}) == []


def test_run_modes_flags_a_case_whose_test_file_is_missing():
    fails = _rm(_E, dry={"x/a.sh": ("bash", "t/gone.sh", "x/a.sh")})
    assert any("does not exist" in f for f in fails)


def test_run_modes_flags_a_test_that_never_mentions_the_dry_run():
    fails = _rm(
        _E,
        dry={"x/a.sh": ("bash", "t/test.sh", "x/a.sh")},
        tests={"t/test.sh": "echo hi"},
    )
    assert any("never mentions the dry run" in f for f in fails)


def test_run_modes_flags_a_non_declaring_library_script_with_no_refusal_case():
    fails = _rm({**_E, "dry_run": False})
    assert fails == [
        "no executing dry-run refusal case: m/stone-b.json profile sd script x/a.sh"
    ]


def test_run_modes_flags_a_stale_case():
    fails = _rm(
        _E,
        dry={
            "x/a.sh": ("bash", "t/test.sh", "x/a.sh"),
            "x/gone.sh": ("bash", "t/test.sh"),
        },
    )
    assert any("stale dry-run case: x/gone.sh" in f for f in fails)


def test_run_modes_flags_a_nonwriter_declaring_dry_run():
    fails = _rm(_E, table={"x/a.sh": ("nonwriter", "image")})
    assert any("declares dry_run" in f for f in fails)


_FWUP_OK = (
    ". ./avocado-safe-disk.sh\n"
    "avocado_safe_disk_modes sd 1 1 || exit 1\n"
    "fwup_task=$(avocado_safe_disk_fwup_task) || exit 1\n"
    'avocado_safe_disk_write fwup -a -u -i a -d "$dev" -t "$fwup_task"\n'
)


def test_fwup_check_passes_a_script_honouring_the_task():
    assert fwup_failures({"x/a.sh": _FWUP_OK}) == []


def test_fwup_check_flags_a_script_ignoring_the_task():
    bad = _FWUP_OK.replace('-t "$fwup_task"', "-t complete")
    assert any("ignores FWUP_TASK" in f for f in fwup_failures({"x/a.sh": bad}))


def test_fwup_check_flags_a_script_that_never_reads_the_task():
    bad = _FWUP_OK.replace("fwup_task=$(avocado_safe_disk_fwup_task) || exit 1\n", "")
    assert any(
        "never calls avocado_safe_disk_fwup_task" in f
        for f in fwup_failures({"x/a.sh": bad})
    )


def test_fwup_check_flags_a_fwup_script_outside_the_library():
    text = 'fwup -a -i a -d "$dev" -t complete\n'
    assert any(
        "neither the task nor a refusal" in f for f in fwup_failures({"x/a.sh": text})
    )


def test_fwup_check_accepts_a_script_that_refuses_a_non_complete_task():
    text = _FWUP_OK.replace("sd 1 1", "sd 1 0").replace(
        "fwup_task=$(avocado_safe_disk_fwup_task) || exit 1\n", ""
    )
    text = text.replace('-t "$fwup_task"', "-t complete")
    assert fwup_failures({"x/a.sh": text}) == []


def test_fwup_check_ignores_archive_to_image_file_builds():
    text = 'fwup -a -i a -d "${archive_image}" -t complete\n'
    assert fwup_failures({"x/a.sh": text}) == []
