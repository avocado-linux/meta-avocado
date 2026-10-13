"""Regression baseline for the media avocado-flash already supports.

Recorded before the ssh-emmc dispatch is added, so the dispatch change can be
shown not to alter the sd path or argument handling. The golden is compared
byte for byte: one extra, missing or changed line fails.

The argparse cases depend on the interpreter's message wording (3.14 when
recorded); a Python upgrade that rewords argparse errors is a reason to review
the golden in its own change, never to regenerate it to make a run pass.
"""

from __future__ import annotations

import pytest

import media_fixtures as mf

GOLDEN = mf.GOLDEN_DIR / "existing-media-sd-dryrun.txt"

SD_DRYRUN_ARGV = ["--deploy", "{deploy}", "--dry-run", "sd", mf.SD_DEVICE]
ARG_ERROR_CASES = {
    "unknown-medium": ["floppy"],
    "unknown-option": ["--bogus", "sd", mf.SD_DEVICE],
}


@pytest.fixture
def golden():
    return mf.golden_cases(GOLDEN)


@pytest.fixture
def module():
    return mf.load_avocado_flash()


def run_sd_dryrun(tmp_path, module, monkeypatch):
    deploy = mf.make_deploy(tmp_path)
    bindir, log = mf.make_stub_bin(tmp_path)
    guarded = []
    # The one substitution: no stub can make a regular path a whole-disk block
    # device, so the guard is recorded instead of run.
    monkeypatch.setattr(module, "assert_safe_block_device", guarded.append)
    argv = [a.format(deploy=deploy) for a in SD_DRYRUN_ARGV]
    result = mf.run_main_in_process(module, argv, monkeypatch, bindir)
    return argv, result, guarded, log


def test_golden_holds_exactly_the_recorded_cases(golden):
    assert sorted(golden) == sorted(["sd-dryrun", *ARG_ERROR_CASES])


def test_loader_imports_the_extensionless_script_without_running_it(module):
    assert module.__file__ == str(mf.SCRIPT)
    assert callable(module.main) and callable(module.build_parser)


def test_sd_dryrun_matches_golden_byte_for_byte(tmp_path, module, monkeypatch, golden):
    argv, result, _, _ = run_sd_dryrun(tmp_path, module, monkeypatch)
    assert mf.render_case("sd-dryrun", argv, result, tmp_path) == golden["sd-dryrun"]


def test_sd_dryrun_executes_no_tool_and_still_reaches_the_device_guard(
    tmp_path, module, monkeypatch
):
    _, result, guarded, log = run_sd_dryrun(tmp_path, module, monkeypatch)
    assert result.exit == 0
    assert guarded == [mf.SD_DEVICE]
    assert log.read_text() == ""


@pytest.mark.parametrize("case", sorted(ARG_ERROR_CASES))
def test_argument_error_matches_golden_byte_for_byte(tmp_path, golden, case):
    bindir, log = mf.make_stub_bin(tmp_path)
    argv = ARG_ERROR_CASES[case]
    result = mf.run_script(argv, tmp_path, bindir)
    assert result.exit == 2
    assert mf.render_case(case, argv, result, tmp_path) == golden[case]
    assert log.read_text() == ""
