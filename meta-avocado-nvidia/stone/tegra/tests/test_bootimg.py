"""boot.img repack at provision time, and the no-kernel fallbacks."""

import pytest

from avocado_tegraflash import EngineError, bootimg

PINS_ENV = "avocado.root_partuuid=AAA avocado.root_partuuid_b=BBB"


class FakeRunner:
    def __init__(self, status=0):
        self.calls = []
        self.status = status

    def run(self, argv, *, cwd=None, env=None):
        self.calls.append((list(argv), cwd, env))
        return self.status

    def capture(self, argv, *, cwd=None, env=None, discard_stderr=False, timeout=None):  # pragma: no cover - not used here
        raise AssertionError("repack must not capture")


@pytest.fixture
def staged(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "initrd.cpio").write_bytes(b"cpio")
    kernel = tmp_path / "Image"
    kernel.write_bytes(b"kernel")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    mkbootimg = bindir / "mkbootimg"
    mkbootimg.write_text("#!/bin/sh\n")
    mkbootimg.chmod(0o755)
    env = {"PATH": f"{tmp_path / 'nope'}:{bindir}", "AVOCADO_KERNEL_CMDLINE_EXTRA": PINS_ENV}
    return work, kernel, env, mkbootimg


def do_repack(runner, staged, **over):
    work, kernel, env, _ = staged
    args = dict(
        work_dir=work, kernel_image=str(kernel), initramfs_name="initrd.cpio", env=env, version="6.12.1"
    )
    args.update(over)
    logged = []
    bootimg.repack(runner, log=logged.append, **args)
    return logged


def test_repack_runs_the_helper_with_the_oracle_argument_order(staged):
    runner = FakeRunner()
    do_repack(runner, staged)
    work, kernel, _, mkbootimg = staged
    assert runner.calls[0][0] == [
        "avocado-tegra-bootimg",
        str(mkbootimg),
        f"{work}/boot.img",
        str(kernel),
        f"{work}/initrd.cpio",
        f"{work}/boot.img",
    ]


class RewritingRunner(FakeRunner):
    """Stands in for the boot image helper: reads the base image, then rewrites it in place."""

    def run(self, argv, *, cwd=None, env=None):
        base, out = argv[2], argv[-1]
        with open(base, "rb") as fh:
            self.base_seen = fh.read()
        with open(out, "wb") as fh:
            fh.write(b"packed")
        return super().run(argv, cwd=cwd, env=env)


@pytest.mark.deviation("symlink-destination-replaced")
def test_repack_copies_a_staged_boot_img_link_so_the_link_target_is_not_written(staged, tmp_path):
    work, _, _, _ = staged
    outside = tmp_path / "data" / "boot.img"
    outside.parent.mkdir()
    outside.write_bytes(b"original")
    (work / "boot.img").symlink_to(outside)
    runner = RewritingRunner()
    do_repack(runner, staged)
    boot = work / "boot.img"
    assert (boot.is_symlink(), boot.read_bytes(), outside.read_bytes(), runner.base_seen) == (
        False, b"packed", b"original", b"original"
    )


def test_repack_passes_the_given_env_through_unchanged(staged):
    runner = FakeRunner()
    do_repack(runner, staged)
    assert runner.calls[0][2] == staged[2]


def test_repack_announces_the_pack_then_the_result(staged):
    logged = do_repack(FakeRunner(), staged)
    assert logged == [
        f"Packing boot.img from kernel 6.12.1 (Image={staged[1]})",
        "boot.img repacked at provision time",
    ]


def test_repack_prints_a_question_mark_for_an_unknown_kernel_version(staged):
    logged = do_repack(FakeRunner(), staged, version="")
    assert logged[0] == f"Packing boot.img from kernel ? (Image={staged[1]})"


def test_repack_refuses_a_kernel_image_that_is_absent_before_running_anything(staged):
    runner = FakeRunner()
    missing = staged[0] / "no-such-Image"
    with pytest.raises(EngineError, match=f"AVOCADO_PROVISION_KERNEL_IMAGE={missing} not found"):
        do_repack(runner, staged, kernel_image=str(missing))
    assert runner.calls == []


def test_repack_refuses_a_kernel_path_that_is_a_directory(staged):
    runner = FakeRunner()
    with pytest.raises(EngineError, match="not found"):
        do_repack(runner, staged, kernel_image=str(staged[0]))
    assert runner.calls == []


def test_repack_refuses_an_initramfs_that_is_not_staged_before_running_anything(staged):
    runner = FakeRunner()
    with pytest.raises(EngineError, match=f"initramfs cpio not staged at {staged[0]}/other.cpio"):
        do_repack(runner, staged, initramfs_name="other.cpio")
    assert runner.calls == []


def test_repack_runs_the_helper_in_the_callers_directory_like_the_oracle(staged):
    # Oracle 438: the script only changes directory at 683, so the helper
    # starts wherever the script was started.
    runner = FakeRunner()
    do_repack(runner, staged)
    assert runner.calls[0][1] is None


def test_repack_names_the_initramfs_by_its_basename(staged):
    runner = FakeRunner()
    do_repack(runner, staged, initramfs_name="sub/initrd.cpio")
    assert runner.calls[0][0][4] == f"{staged[0]}/initrd.cpio"


@pytest.mark.deviation("mkbootimg-missing-refused")
def test_repack_refuses_when_mkbootimg_is_not_on_the_env_path(staged):
    # Oracle line 438: `command -v mkbootimg` expands to nothing and the helper
    # starts with an empty argument.
    runner = FakeRunner()
    work, kernel, env, _ = staged
    with pytest.raises(EngineError, match="mkbootimg"):
        do_repack(runner, staged, env={**env, "PATH": "/nonexistent-dir"})
    assert runner.calls == []


def test_repack_resolves_mkbootimg_only_on_the_env_path_not_the_process_path(staged, monkeypatch):
    bindir = staged[0].parent / "bin"
    monkeypatch.setenv("PATH", str(bindir))
    with pytest.raises(EngineError, match="mkbootimg"):
        do_repack(FakeRunner(), staged, env={"PATH": "/nonexistent-dir"})


def test_repack_fails_on_a_nonzero_helper_exit_without_claiming_success(staged):
    logged = []
    work, kernel, env, _ = staged
    with pytest.raises(EngineError, match=r"avocado-tegra-bootimg failed \(exit 3\)"):
        bootimg.repack(
            FakeRunner(status=3),
            work_dir=work,
            kernel_image=str(kernel),
            initramfs_name="initrd.cpio",
            env=env,
            version="1",
            log=logged.append,
        )
    assert "boot.img repacked at provision time" not in logged


# ---- no kernel image ----------------------------------------------------


@pytest.mark.parametrize("cmdline,extra", [("console=x", ""), ("", "hugepages=2"), ("a", "b")])
def test_refuse_cmdline_without_kernel_refuses_when_either_is_set(cmdline, extra):
    with pytest.raises(EngineError) as info:
        bootimg.refuse_cmdline_without_kernel(cmdline, extra)
    assert str(info.value) == (
        "kernel.cmdline / cmdline_extra is set, but no kernel Image was staged\n"
        "       (AVOCADO_PROVISION_KERNEL_IMAGE) to repack boot.img with it."
    )


def test_refuse_cmdline_without_kernel_accepts_two_empty_values():
    assert bootimg.refuse_cmdline_without_kernel("", "") is None


def test_warn_prebuilt_boot_image_prints_the_oracle_text_in_order():
    logged = []
    bootimg.warn_prebuilt_boot_image(logged.append)
    assert logged == [
        "AVOCADO_PROVISION_KERNEL_IMAGE not set - using prebuilt boot.img from BSP",
        "WARNING: the prebuilt boot.img names no rootfs PARTUUID. With a boot signal",
        "         (BootCurrent) the initrd takes APP on the disk UEFI booted from.",
        "         With none, the first APP to appear boots, so an SD card that",
        "         enumerates before the NVMe wins. Two or more APP disks are caught",
        "         only if all are present at that moment; then a root= naming",
        "         exactly one of them settles it, and otherwise the initrd stops.",
    ]


# ---- end to end with partuuid -------------------------------------------


def test_pins_reach_the_helper_env_and_the_layout_together(staged):
    from avocado_tegraflash import partuuid

    work, kernel, env, _ = staged
    pins = ("11111111-2222-4333-8444-555555555555", "AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE")
    env = {**env, "AVOCADO_KERNEL_CMDLINE_EXTRA": partuuid.append_cmdline("", pins)}
    (work / "external-flash.xml.in").write_text("<a>APPUUID_b</a><b>APPUUID </b>")
    runner = FakeRunner()
    logged = do_repack(runner, staged, env=env)
    partuuid.apply_layout(work, pins)
    layout = (work / "external-flash.xml.in").read_text()
    assert (
        runner.calls[0][2]["AVOCADO_KERNEL_CMDLINE_EXTRA"],
        logged[0].startswith("Packing boot.img from kernel 6.12.1 (Image="),
        pins[0] in layout and pins[1] in layout and "APPUUID" not in layout,
    ) == (
        f"avocado.root_partuuid={pins[0]} avocado.root_partuuid_b={pins[1]}",
        True,
        True,
    )


# ---- falsifiers -----------------------------------------------------------


def test_falsifier_missing_kernel_check_removed_lets_repack_run_the_helper(staged, mutant):
    mod = mutant("bootimg.py", "if not Path(kernel_image).is_file():", "if False:")
    runner = FakeRunner()
    mod.repack(runner, work_dir=staged[0], kernel_image=str(staged[0] / "gone"),
               initramfs_name="initrd.cpio", env=staged[2], version="1", log=lambda _t: None)
    assert len(runner.calls) == 1


def test_falsifier_nonzero_exit_ignored_reports_success(staged, mutant):
    mod = mutant("bootimg.py", "if status != 0:", "if False:")
    logged = []
    mod.repack(FakeRunner(status=3), work_dir=staged[0], kernel_image=str(staged[1]),
               initramfs_name="initrd.cpio", env=staged[2], version="1", log=logged.append)
    assert "boot.img repacked at provision time" in logged
