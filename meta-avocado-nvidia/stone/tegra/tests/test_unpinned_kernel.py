"""An unpinned kernel is refused before staging or board contact unless the opt-out is exactly 1."""

import pytest

from avocado_tegraflash.cli import main
from test_cli_flow import make_rig

KERNEL = "AVOCADO_PROVISION_KERNEL_IMAGE"
OPT_OUT = "AVOCADO_PROVISION_ALLOW_UNPINNED_KERNEL"


def _staged(rig) -> bool:
    return rig.work.exists()


def test_no_kernel_and_no_opt_out_is_refused_naming_both_variables(tmp_path, capsys):
    rig = make_rig(tmp_path, unpinned_ok=False)
    rc, _, err = rig.go(main, capsys)
    assert (rc != 0, KERNEL in err, OPT_OUT in err, _staged(rig), rig.runner.calls) == (True, True, True, False, [])


def test_refusal_applies_under_prepare_only(tmp_path, capsys):
    rig = make_rig(tmp_path, unpinned_ok=False)
    rc, _, err = rig.go(main, capsys, argv=["--prepare-only"])
    assert (rc != 0, KERNEL in err, OPT_OUT in err, _staged(rig), rig.runner.calls) == (True, True, True, False, [])


def test_opt_out_one_lifts_the_refusal_and_keeps_the_prebuilt_warning(tmp_path, capsys):
    rig = make_rig(tmp_path, unpinned_ok=False, env={OPT_OUT: "1"})
    rc, out, _ = rig.go(main, capsys)
    assert (rc, "prebuilt boot.img" in out) == (0, True)


@pytest.mark.parametrize("value", ["yes", "true", "0", "", "11", " 1"])
def test_any_other_opt_out_value_keeps_the_refusal(tmp_path, capsys, value):
    rig = make_rig(tmp_path, unpinned_ok=False, env={OPT_OUT: value})
    rc, _, err = rig.go(main, capsys)
    assert (rc != 0, OPT_OUT in err, _staged(rig)) == (True, True, False)


def test_a_pinned_kernel_needs_no_opt_out(tmp_path, capsys):
    rig = make_rig(tmp_path, kernel=True)
    rc, _, _ = rig.go(main, capsys)
    assert rc == 0
