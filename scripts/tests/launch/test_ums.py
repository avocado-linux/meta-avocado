"""ums session: stale export, before/after listings, release on every exit."""

import pytest

from avocado_flash_launch.envmap import LauncherError
from avocado_flash_launch.ums import ums_session


class FakeHost:
    """Records every console-facing call in order; listings come from a script."""

    def __init__(self, before, after, stale=False, stale_stays=False, expose_raises=None):
        self.calls = []
        self.before = set(before)
        self.after = set(after)
        self.exported = False
        self.stale = stale
        self.stale_stays = stale_stays
        self.expose_raises = expose_raises
        self.gadget_polls = 0

    def UBoot(self, port):
        self.calls.append(("UBoot", port))
        return "ub"

    def interrupt_to_uboot(self, ub):
        self.calls.append(("interrupt", ub))

    def ums_release(self, ub, quiet=False):
        self.calls.append(("release", quiet))
        if not self.stale_stays:
            self.stale = False

    def usb_gadget_present(self):
        self.gadget_polls += 1
        return self.stale

    def block_devices(self):
        self.calls.append(("listing",))
        return set(self.after) if self.exported else set(self.before)

    def ums_expose(self, ub, controller, dev, timeout=25.0):
        self.calls.append(("expose", controller, dev))
        if self.expose_raises:
            raise self.expose_raises
        self.exported = True
        return "ignored"


def run(host, body=lambda d: d, **kw):
    kw.setdefault("sleep", lambda s: None)
    with ums_session(host, "/dev/ttyACM0", 0, "mmc1", log=lambda m: None, **kw) as dev:
        return body(dev)


def names(host):
    return [c[0] for c in host.calls]


def test_one_new_disk_is_yielded_and_released():
    host = FakeHost({"sda", "nvme0n1"}, {"sda", "nvme0n1", "sdb"})
    assert run(host) == "/dev/sdb"
    assert host.calls == [
        ("UBoot", "/dev/ttyACM0"),
        ("interrupt", "ub"),
        ("listing",),
        ("expose", 0, "mmc1"),
        ("listing",),
        ("release", False),
    ]


def test_two_new_disks_refuse_listing_both_and_release():
    host = FakeHost({"sda"}, {"sda", "sdb", "sdc"})
    with pytest.raises(LauncherError) as e:
        run(host)
    assert "sdb" in str(e.value) and "sdc" in str(e.value)
    assert names(host)[-1] == "release"


def test_no_new_disk_refuses_and_releases():
    host = FakeHost({"sda"}, {"sda"})
    with pytest.raises(LauncherError, match="no exported disk"):
        run(host)
    assert names(host)[-1] == "release"


def test_loop_and_ram_devices_are_not_candidates():
    host = FakeHost({"sda"}, {"sda", "loop3", "zram0", "ram1", "sdb"})
    assert run(host) == "/dev/sdb"


def test_release_after_profile_refusal():
    host = FakeHost({"sda"}, {"sda", "sdb"})

    def body(dev):
        raise LauncherError("profile refused")

    with pytest.raises(LauncherError, match="profile refused"):
        run(host, body)
    assert names(host).count("release") == 1
    assert names(host)[-1] == "release"


def test_release_after_interrupt():
    host = FakeHost({"sda"}, {"sda", "sdb"})

    def body(dev):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(host, body)
    assert names(host)[-1] == "release"


def test_expose_raise_with_gadget_present_releases_once():
    host = FakeHost({"sda"}, {"sda"}, expose_raises=RuntimeError("several disks"))
    state = {"n": 0}

    def probe():
        # first call is the stale check (absent); later calls see the new export
        state["n"] += 1
        return state["n"] > 1

    host.usb_gadget_present = probe
    with pytest.raises(RuntimeError):
        run(host)
    assert names(host).count("release") == 1
    assert host.calls[-1] == ("release", True)


def test_expose_raise_with_gadget_absent_does_not_release():
    host = FakeHost({"sda"}, {"sda"}, expose_raises=RuntimeError("serial dead"))
    with pytest.raises(RuntimeError):
        run(host)
    assert "release" not in names(host)


def test_expose_raise_without_probe_does_not_release():
    class NoProbe(FakeHost):
        usb_gadget_present = None

    host = NoProbe({"sda"}, {"sda"}, expose_raises=RuntimeError("serial dead"))
    with pytest.raises(RuntimeError):
        run(host)
    assert "release" not in names(host)


def test_expose_raise_with_failing_probe_does_not_release():
    host = FakeHost({"sda"}, {"sda"}, expose_raises=RuntimeError("x"))
    calls = {"n": 0}

    def probe():
        calls["n"] += 1
        if calls["n"] > 1:
            raise OSError("lsusb missing")
        return False

    host.usb_gadget_present = probe
    with pytest.raises(RuntimeError):
        run(host)
    assert "release" not in names(host)


def test_no_release_when_console_never_reached():
    host = FakeHost({"sda"}, {"sda", "sdb"})

    def boom(ub):
        raise RuntimeError("no prompt")

    host.interrupt_to_uboot = boom
    with pytest.raises(RuntimeError):
        run(host)
    assert "release" not in names(host)
    assert "expose" not in names(host)


def test_stale_export_released_before_first_listing():
    host = FakeHost({"sda"}, {"sda", "sdb"}, stale=True)
    assert run(host) == "/dev/sdb"
    seq = names(host)
    assert seq.index("release") < seq.index("listing")
    assert seq.count("release") == 2
    assert host.calls[seq.index("release")] == ("release", True)


def test_stale_export_that_stays_refuses_without_exporting_or_releasing_again():
    host = FakeHost({"sda"}, {"sda", "sdb"}, stale=True, stale_stays=True)
    ticks = iter(range(0, 1000))
    with pytest.raises(LauncherError, match="unplug the OTG cable"):
        run(host, clock=lambda: next(ticks), stale_wait=5)
    assert names(host).count("release") == 1
    assert "expose" not in names(host)
    assert "listing" not in names(host)


def test_dry_run_body_gets_same_enter_exit_sequence():
    host = FakeHost({"sda"}, {"sda", "sdb"})
    seen = []
    run(host, lambda d: seen.append(("dry run", d)))
    assert seen == [("dry run", "/dev/sdb")]
    assert names(host) == ["UBoot", "interrupt", "listing", "expose", "listing", "release"]
