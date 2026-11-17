"""USB listing, device pinning and the pre-write recheck."""

import pytest

from avocado_flash_tegra import FlashError
from avocado_flash_tegra.rcm import (
    DeviceSetChanged,
    ListingFailed,
    MultipleRecoveryDevices,
    NoRecoveryDevice,
    UsbDevice,
    list_usb,
    pin,
    recheck,
)

EXPECTED = "0955:7523"

HUB = "Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub"
ORIN = "Bus 003 Device 005: ID 0955:7523 NVIDIA Corp. APX"
ORIN2 = "Bus 003 Device 006: ID 0955:7523 NVIDIA Corp. APX"
DEVICE_MODE = "Bus 003 Device 007: ID 0955:7020 NVIDIA Corp. L4T (Linux for Tegra) running on Tegra"
OTHER_MODULE = "Bus 003 Device 008: ID 0955:7323 NVIDIA Corp. APX"


class FakeRunner:
    def __init__(self, stdout="", rc=0):
        self.stdout = stdout
        self.rc = rc
        self.calls = []

    def capture(self, argv):
        self.calls.append(list(argv))
        return self.rc, self.stdout


def listing(*lines):
    return "\n".join(lines) + "\n"


def devices(*lines):
    return list_usb(FakeRunner(listing(*lines)))


def test_list_usb_parses_lines_and_ignores_others():
    got = devices(HUB, "garbage line", ORIN)
    assert got == [
        UsbDevice("001", "001", "1d6b", "0002", "Linux Foundation 2.0 root hub"),
        UsbDevice("003", "005", "0955", "7523", "NVIDIA Corp. APX"),
    ]


def test_usb_device_id_and_path_are_lowercase_and_bus_dev():
    d = devices("Bus 003 Device 005: ID 0955:7523 NVIDIA Corp. APX")[0]
    assert d.id == "0955:7523"
    assert d.path == "003:005"
    upper = devices("Bus 003 Device 005: ID 0955:7A23 X")[0]
    assert upper.id == "0955:7a23"


def test_pin_one_device_returns_it():
    got = pin(devices(HUB, ORIN), EXPECTED)
    assert got.path == "003:005"
    assert got.id == EXPECTED


def test_pin_none_gives_recovery_guidance():
    with pytest.raises(NoRecoveryDevice) as exc:
        pin(devices(HUB), EXPECTED)
    text = str(exc.value)
    assert "recovery jumper" in text
    assert "USB cable" in text
    assert "power-cycle" in text
    assert "running Linux" not in text


def test_pin_multiple_devices_refused_listing_each():
    with pytest.raises(MultipleRecoveryDevices) as exc:
        pin(devices(ORIN, ORIN2), EXPECTED)
    text = str(exc.value)
    assert "003:005" in text
    assert "003:006" in text
    assert "0955:7523" in text


def test_pin_multiple_devices_even_when_ids_differ():
    with pytest.raises(MultipleRecoveryDevices):
        pin(devices(ORIN, OTHER_MODULE), EXPECTED)


def test_pin_board_in_device_mode_says_not_recovery():
    with pytest.raises(NoRecoveryDevice) as exc:
        pin(devices(HUB, DEVICE_MODE), EXPECTED)
    text = str(exc.value)
    assert "running Linux and is not in recovery mode" in text
    assert "recovery jumper" in text


def test_pin_device_mode_board_is_not_a_candidate_next_to_a_recovery_board():
    got = pin(devices(DEVICE_MODE, ORIN), EXPECTED)
    assert got.path == "003:005"


def test_pin_wrong_module_prints_both_ids():
    with pytest.raises(FlashError) as exc:
        pin(devices(OTHER_MODULE), EXPECTED)
    text = str(exc.value)
    assert "0955:7323" in text
    assert "0955:7523" in text
    assert not isinstance(exc.value, (NoRecoveryDevice, MultipleRecoveryDevices))


def test_pin_ignores_non_nvidia_devices():
    with pytest.raises(NoRecoveryDevice):
        pin(devices("Bus 001 Device 002: ID 1fc9:0146 NXP Semiconductors"), EXPECTED)


def test_list_usb_exit_1_is_listing_failed_without_recovery_guidance():
    with pytest.raises(ListingFailed) as exc:
        list_usb(FakeRunner("", rc=1))
    text = str(exc.value)
    assert "could not be listed" in text
    assert "recovery" not in text.lower()
    assert isinstance(exc.value, FlashError)


def test_list_usb_cannot_start_is_listing_failed():
    with pytest.raises(ListingFailed) as exc:
        list_usb(FakeRunner("", rc=127))
    text = str(exc.value)
    assert "could not be listed" in text
    assert "recovery" not in text.lower()
    assert not isinstance(exc.value, NoRecoveryDevice)


def test_recheck_same_single_device_passes():
    pinned = pin(devices(ORIN), EXPECTED)
    recheck(pinned, devices(HUB, ORIN), EXPECTED)


def test_recheck_second_board_raises_device_set_changed():
    pinned = pin(devices(ORIN), EXPECTED)
    with pytest.raises(DeviceSetChanged) as exc:
        recheck(pinned, devices(ORIN, ORIN2), EXPECTED)
    assert "changed" in str(exc.value)


def test_recheck_pinned_board_gone_raises_device_set_changed():
    pinned = pin(devices(ORIN), EXPECTED)
    with pytest.raises(DeviceSetChanged):
        recheck(pinned, devices(HUB), EXPECTED)


def test_recheck_a_different_board_at_another_path_raises():
    pinned = pin(devices(ORIN), EXPECTED)
    with pytest.raises(DeviceSetChanged):
        recheck(pinned, devices(ORIN2), EXPECTED)


def test_recheck_ignores_device_mode_board():
    pinned = pin(devices(ORIN), EXPECTED)
    recheck(pinned, devices(ORIN, DEVICE_MODE), EXPECTED)


def test_runner_is_only_asked_for_lsusb():
    runner = FakeRunner(listing(HUB, ORIN))
    list_usb(runner)
    list_usb(runner)
    assert runner.calls == [["lsusb"], ["lsusb"]]


def test_rcm_module_does_not_import_subprocess():
    import avocado_flash_tegra.rcm as rcm

    assert not hasattr(rcm, "subprocess")
