"""set_first: the target medium becomes the firmware's first boot choice."""

import hashlib
from pathlib import Path

import pytest

from avocado_tegraflash import EngineError, Media, bootpriority

NODE = (
    "/fragment@0/__overlay__/firmware/uefi/variables/"
    "gNVIDIATokenSpaceGuid/DefaultBootPriority"
)
STOCK = "usb,nvme,emmc,sd,ufs"
PKG_DIR = Path(bootpriority.__file__).parent


class FakeRunner:
    """fdtget/fdtput over a dtbo stand-in whose whole content is the property value."""

    def __init__(self, *, get_status=0, put_status=0, put_takes=True, empty=False):
        self.calls = []
        self.capture_options = []
        self.get_status = get_status
        self.put_status = put_status
        self.put_takes = put_takes
        self.empty = empty

    def run(self, argv, *, cwd=None, env=None):
        self.calls.append((list(argv), env))
        assert argv[0] == "fdtput"
        if self.put_status == 0 and self.put_takes:
            Path(argv[3]).write_text(argv[-1])
        return self.put_status

    def capture(self, argv, *, cwd=None, env=None, discard_stderr=False, timeout=None):
        self.calls.append((list(argv), env))
        self.capture_options.append((discard_stderr, timeout))
        assert argv[0] == "fdtget"
        if self.get_status != 0:
            return self.get_status, ""
        if self.empty and not Path(argv[3]).read_text():
            return 0, "\n"
        return 0, Path(argv[3]).read_text() + "\n"


def make_work(tmp_path, value=STOCK):
    work = tmp_path / "work"
    work.mkdir()
    (work / "L4TConfiguration.dtbo").write_text(value)
    return work


def value_of(work):
    return (work / "L4TConfiguration.dtbo").read_text()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("media", "want"),
    [
        (Media.NVME, "nvme,usb,emmc,sd,ufs"),
        (Media.SD, "sd,usb,nvme,emmc,ufs"),
        (Media.EMMC, "emmc,usb,nvme,sd,ufs"),
    ],
)
def test_media_class_goes_first_and_the_rest_keep_stock_order(tmp_path, media, want):
    work = make_work(tmp_path)
    bootpriority.set_first(FakeRunner(), work, media, env={}, log=lambda _: None)
    assert value_of(work) == want


def test_stock_list_already_led_by_the_media_is_unchanged(tmp_path):
    work = make_work(tmp_path, "nvme,usb,emmc,sd,ufs")
    new, was = bootpriority.set_first(
        FakeRunner(), work, Media.NVME, env={}, log=lambda _: None
    )
    assert (new, was) == ("nvme,usb,emmc,sd,ufs", "nvme,usb,emmc,sd,ufs")


@pytest.mark.parametrize(
    ("stock", "want"),
    [
        ("usb,nvme,", "sd,usb,nvme"),  # one trailing delimiter ends the last field
        ("usb,nvme,,", "sd,usb,nvme,"),  # a second one leaves an empty field
        ("usb,,nvme", "sd,usb,,nvme"),  # a middle empty field stays
        (",", "sd,"),
    ],
)
def test_empty_fields_follow_read_ra_of_the_oracle(tmp_path, stock, want):
    # Oracle line 611: `IFS=, read -ra` drops exactly one trailing empty field.
    work = make_work(tmp_path, stock)
    new, _ = bootpriority.set_first(FakeRunner(), work, Media.SD, env={}, log=lambda _: None)
    assert new == want


def test_media_absent_from_stock_is_prepended(tmp_path):
    work = make_work(tmp_path, "usb,nvme")
    new, _ = bootpriority.set_first(
        FakeRunner(), work, Media.SD, env={}, log=lambda _: None
    )
    assert new == "sd,usb,nvme"


def test_empty_stock_value_yields_the_media_alone(tmp_path):
    work = make_work(tmp_path, "")
    new, was = bootpriority.set_first(
        FakeRunner(empty=True), work, Media.SD, env={}, log=lambda _: None
    )
    assert (new, was) == ("sd", "")


def test_duplicate_of_the_media_in_stock_is_collapsed(tmp_path):
    work = make_work(tmp_path, "usb,sd,sd,ufs")
    new, _ = bootpriority.set_first(
        FakeRunner(), work, Media.SD, env={}, log=lambda _: None
    )
    assert new == "sd,usb,ufs"


def test_sd_on_the_stock_list_returns_the_new_and_old_values(tmp_path):
    work = make_work(tmp_path)
    result = bootpriority.set_first(
        FakeRunner(), work, Media.SD, env={}, log=lambda _: None
    )
    assert result == ("sd,usb,nvme,emmc,ufs", STOCK)


def test_prints_the_priority_line_exactly(tmp_path):
    work = make_work(tmp_path)
    lines = []
    bootpriority.set_first(FakeRunner(), work, Media.SD, env={}, log=lines.append)
    assert lines == [
        "UEFI DefaultBootPriority: sd,usb,nvme,emmc,ufs "
        "(was usb,nvme,emmc,sd,ufs)"
    ]


def test_tools_run_with_the_oracle_argv_and_the_flash_env(tmp_path):
    work = make_work(tmp_path)
    runner = FakeRunner()
    env = {"PATH": "/x"}
    bootpriority.set_first(runner, work, Media.SD, env=env, log=lambda _: None)
    dtbo = str(work / "L4TConfiguration.dtbo")
    assert runner.calls == [
        (["fdtget", "-t", "s", dtbo, NODE, "data"], env),
        (["fdtput", "-t", "s", dtbo, NODE, "data", "sd,usb,nvme,emmc,ufs"], env),
        (["fdtget", "-t", "s", dtbo, NODE, "data"], env),
    ]


def test_linked_dtbo_becomes_a_regular_copy_and_the_bsp_file_keeps_its_hash(tmp_path):
    bsp = tmp_path / "staged.dtbo"
    bsp.write_text(STOCK)
    before = sha(bsp)
    work = tmp_path / "work"
    work.mkdir()
    (work / "L4TConfiguration.dtbo").symlink_to(bsp)
    bootpriority.set_first(FakeRunner(), work, Media.SD, env={}, log=lambda _: None)
    link = work / "L4TConfiguration.dtbo"
    assert (link.is_symlink(), value_of(work), sha(bsp)) == (
        False,
        "sd,usb,nvme,emmc,ufs",
        before,
    )


def test_link_to_a_file_outside_the_work_dir_leaves_that_file_unmodified(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "stock.dtbo"
    target.write_text(STOCK)
    before = (sha(target), target.stat().st_mtime_ns, target.stat().st_ino)
    work = tmp_path / "work"
    work.mkdir()
    (work / "L4TConfiguration.dtbo").symlink_to(target)
    bootpriority.set_first(FakeRunner(), work, Media.SD, env={}, log=lambda _: None)
    assert (sha(target), target.stat().st_mtime_ns, target.stat().st_ino) == before
    assert value_of(work) == "sd,usb,nvme,emmc,ufs"


def test_link_whose_copy_fails_raises_engine_error_not_a_bare_oserror(tmp_path):
    class StockRunner(FakeRunner):
        def capture(self, argv, **kwargs):
            return 0, STOCK + "\n"

    elsewhere = tmp_path / "a-directory"
    elsewhere.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    (work / "L4TConfiguration.dtbo").symlink_to(elsewhere)
    with pytest.raises(EngineError, match="cannot copy"):
        bootpriority.set_first(StockRunner(), work, Media.SD, env={}, log=lambda _: None)


def test_fdtget_keeps_stderr_and_is_bounded_like_the_oracle(tmp_path):
    work = make_work(tmp_path)
    runner = FakeRunner()
    bootpriority.set_first(runner, work, Media.SD, env={}, log=lambda _: None)
    assert runner.capture_options == [(False, bootpriority.FDTGET_TIMEOUT)] * 2


def test_fdtget_failure_raises_naming_the_overlay(tmp_path):
    work = make_work(tmp_path)
    with pytest.raises(EngineError) as err:
        bootpriority.set_first(
            FakeRunner(get_status=1), work, Media.SD, env={}, log=lambda _: None
        )
    assert str(work / "L4TConfiguration.dtbo") in str(err.value)


def test_overlay_without_the_node_stops_before_any_write(tmp_path):
    work = make_work(tmp_path)
    runner = FakeRunner(get_status=1)
    with pytest.raises(EngineError):
        bootpriority.set_first(runner, work, Media.SD, env={}, log=lambda _: None)
    assert [c[0][0] for c in runner.calls] == ["fdtget"]


def test_fdtput_failure_raises_naming_the_overlay(tmp_path):
    work = make_work(tmp_path)
    with pytest.raises(EngineError) as err:
        bootpriority.set_first(
            FakeRunner(put_status=1), work, Media.SD, env={}, log=lambda _: None
        )
    assert str(work / "L4TConfiguration.dtbo") in str(err.value)


def test_value_that_did_not_take_raises(tmp_path):
    work = make_work(tmp_path)
    with pytest.raises(EngineError) as err:
        bootpriority.set_first(
            FakeRunner(put_takes=False), work, Media.SD, env={}, log=lambda _: None
        )
    assert "did not take" in str(err.value)


def test_nothing_is_printed_when_the_value_did_not_take(tmp_path):
    work = make_work(tmp_path)
    lines = []
    with pytest.raises(EngineError):
        bootpriority.set_first(
            FakeRunner(put_takes=False), work, Media.SD, env={}, log=lines.append
        )
    assert lines == []


def test_mutant_without_media_first_ordering_is_caught(tmp_path, mutant):
    src = (PKG_DIR / "bootpriority.py").read_text()
    assert "[media.value]" in src
    mod = mutant("bootpriority.py", "[media.value]", "[]")
    work = make_work(tmp_path)
    mod.set_first(FakeRunner(), work, Media.SD, env={}, log=lambda _: None)
    assert value_of(work) != "sd,usb,nvme,emmc,ufs"


def test_mutant_that_keeps_the_link_alters_the_bsp_file(tmp_path, mutant):
    mod = mutant("bootpriority.py", "if dtbo.is_symlink():", "if False:")
    bsp = tmp_path / "staged.dtbo"
    bsp.write_text(STOCK)
    work = tmp_path / "work"
    work.mkdir()
    (work / "L4TConfiguration.dtbo").symlink_to(bsp)
    mod.set_first(FakeRunner(), work, Media.SD, env={}, log=lambda _: None)
    assert bsp.read_text() == "sd,usb,nvme,emmc,ufs"


def test_mutant_without_the_readback_check_accepts_a_value_that_did_not_take(tmp_path, mutant):
    mod = mutant("bootpriority.py", "if got != new:", "if False:")
    work = make_work(tmp_path)
    result = mod.set_first(
        FakeRunner(put_takes=False), work, Media.SD, env={}, log=lambda _: None
    )
    assert result[0] == "sd,usb,nvme,emmc,ufs"
