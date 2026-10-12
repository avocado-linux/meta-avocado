"""Readback for a profile whose arm strategy is none (task 5.13)."""

from __future__ import annotations

import dataclasses

import pytest

from test_cmd_readback_status import dirs, profile, run, script  # noqa: F401
from avocado_flash_remote.ops import RecordingOps

NA_LINE = "boot variables: not applicable (arm strategy none)"


@pytest.fixture
def none_profile(profile):
    return dataclasses.replace(profile, arm=dataclasses.replace(profile.arm, strategy="none", params={}))


def _no_efi(dirs):
    s = script(dirs)
    del s["efibootmgr -v"]
    return s


def test_arm_none_never_calls_efibootmgr_and_exits_0(none_profile, dirs):
    ops = RecordingOps(_no_efi(dirs))
    res, _, lines = run(none_profile, dirs, ops, reference=None)
    assert res.exit_code == 0
    assert not any("efibootmgr" in c for c in ops.log)
    assert NA_LINE in lines
    assert not any("BootOrder" in line for line in lines)
    assert ops.log[0] == "lsblk -dn -o NAME"
    assert ops.log[-1].startswith("umount")


def test_arm_none_ignores_a_differing_reference(none_profile, dirs):
    ops = RecordingOps(_no_efi(dirs))
    res, _, _ = run(none_profile, dirs, ops, reference="9999")
    assert res.exit_code == 0


def test_uefi_still_compares_and_exits_1_on_differing_order(profile, dirs):
    ops = RecordingOps(script(dirs, efi="BootOrder: 0009\n"))
    res, _, lines = run(profile, dirs, ops)
    assert res.exit_code == 1
    assert ops.log[0] == "efibootmgr -v"
    assert NA_LINE not in lines
