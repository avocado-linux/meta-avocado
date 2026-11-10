"""NVIDIA USB listing and recovery-mode detection."""

import pytest

from avocado_tegraflash import EngineError, usb
from avocado_tegraflash.usb import RECOVERY_PIDS, UsbDevice, is_recovery, list_nvidia

APX = "Bus 001 Device 005: ID 0955:7523 NVIDIA Corp. APX"


class CaptureRunner:
    def __init__(self, status=0, out=""):
        self.calls = []
        self.status, self.out = status, out

    def run(self, argv, *, cwd=None, env=None):  # pragma: no cover - not used here
        raise AssertionError("listing must not run")

    def capture(self, argv, *, cwd=None, env=None, discard_stderr=False, timeout=None):
        self.calls.append((list(argv), env))
        return self.status, self.out


def test_recovery_pids_are_the_union_of_engine_script_and_l4t_ids():
    assert RECOVERY_PIDS == (
        "7018", "7418", "7019", "7e19", "7023", "7223", "7323", "7423", "7523", "7623",
        "7819", "7919", "7026", "7226", "7326",
    )


def test_list_nvidia_runs_exactly_lsusb_with_the_vendor_filter_and_env():
    runner = CaptureRunner(out=APX + "\n")
    env = {"PATH": "/x"}
    list_nvidia(runner, env)
    assert runner.calls == [(["lsusb", "-d", "0955:"], env)]


def test_list_nvidia_parses_bus_device_ids_and_description():
    runner = CaptureRunner(out=APX + "\n")
    assert list_nvidia(runner, {}) == [UsbDevice("001", "005", "0955", "7523", "NVIDIA Corp. APX")]


def test_list_nvidia_ignores_malformed_lines_and_blank_output():
    out = "garbage\n\nBus 1 Device 5: ID 0955:7523 NVIDIA\nBus 001 Device 005: ID 0955:75 x\n" + APX + "\n"
    assert [d.device for d in list_nvidia(CaptureRunner(out=out), {})] == ["005"]


def test_list_nvidia_empty_output_gives_no_devices():
    assert list_nvidia(CaptureRunner(out=""), {}) == []


def test_list_nvidia_no_match_status_1_is_an_empty_bus_not_a_failure():
    assert list_nvidia(CaptureRunner(status=1, out=""), {}) == []


@pytest.mark.parametrize("status", [2, 124, 127])
def test_list_nvidia_failed_lsusb_raises_naming_the_status(status):
    with pytest.raises(usb.ListingFailed, match=f"lsusb status {status}") as exc:
        list_nvidia(CaptureRunner(status=status, out=""), {})
    assert isinstance(exc.value, EngineError) and exc.value.status == status


def test_list_nvidia_discards_lsusb_stderr_and_bounds_the_run():
    seen = {}

    class Spy(CaptureRunner):
        def capture(self, argv, *, cwd=None, env=None, discard_stderr=False, timeout=None):
            seen.update(discard_stderr=discard_stderr, timeout=timeout)
            return super().capture(argv, cwd=cwd, env=env)

    list_nvidia(Spy(out=APX + "\n"), {})
    assert seen == {"discard_stderr": True, "timeout": usb.LSUSB_TIMEOUT}
    assert 0 < usb.LSUSB_TIMEOUT <= 10


def test_list_nvidia_description_may_be_empty():
    out = "Bus 002 Device 003: ID 0955:7523 \n"
    assert list_nvidia(CaptureRunner(out=out), {}) == [UsbDevice("002", "003", "0955", "7523", "")]


def test_usb_device_is_frozen():
    dev = UsbDevice("001", "005", "0955", "7523", "x")
    with pytest.raises(Exception):
        dev.bus = "002"  # type: ignore[misc]


@pytest.mark.parametrize("desc", ["NVIDIA Corp. APX", "nvidia corp. apx", "Foo RCM mode", "thing rcm"])
def test_description_with_apx_or_rcm_is_recovery_in_any_case(desc):
    assert is_recovery(UsbDevice("001", "001", "0955", "9999", desc))


@pytest.mark.parametrize("pid", RECOVERY_PIDS)
def test_listed_product_id_is_recovery_without_a_matching_description(pid):
    assert is_recovery(UsbDevice("001", "001", "0955", pid, "NVIDIA Corp."))


def test_device_mode_7020_is_not_recovery():
    assert not is_recovery(UsbDevice("001", "004", "0955", "7020", "NVIDIA Corp. L4T device mode"))


def test_other_vendor_is_not_recovery_even_with_a_listed_pid():
    assert not is_recovery(UsbDevice("001", "001", "1234", "7523", "Foo APX"))


def test_uppercase_listed_pid_is_recovery():
    assert is_recovery(UsbDevice("001", "001", "0955", "7E19", ""))


def test_module_exposes_no_shell_entry_points():
    assert not hasattr(usb, "subprocess")
