"""Tests for the parity comparator and deviation registry."""

import os
import stat
from pathlib import Path

from parity import compare, deviations

UU_A = "11111111-AAAA-4BBB-8CCC-000000000001"
UU_B = "22222222-AAAA-4BBB-8CCC-000000000002"
UU_C = "33333333-AAAA-4BBB-8CCC-000000000003"
UU_D = "44444444-AAAA-4BBB-8CCC-000000000004"


def rec(tool, argv, root, wrapper, uu_a=UU_A, uu_b=UU_B, path_tail="/usr/bin"):
    return {
        "tool": tool,
        "argv": argv,
        "cwd": f"{root}/work",
        "PATH": f"{wrapper}:{root}/build/tegraflash:{path_tail}",
        "PYTHONWARNINGS": "ignore",
        "AVOCADO_KERNEL_CMDLINE_EXTRA": (
            f"quiet avocado.root_partuuid={uu_a} avocado.root_partuuid_b={uu_b}"
        ),
    }


def log(root, wrapper, uu_a=UU_A, uu_b=UU_B, flash_args=None, path_tail="/usr/bin"):
    flash_args = flash_args or ["--erase-nvme", "--erase-spi", f"{root}/images"]
    return [
        rec("lsusb", [], root, wrapper, uu_a, uu_b, path_tail),
        rec("sgdisk", ["-p", f"{root}/x.img"], root, wrapper, uu_a, uu_b, path_tail),
        rec(
            "initrd-flash",
            flash_args + [f"root={uu_a}"],
            root,
            wrapper,
            uu_a,
            uu_b,
            path_tail,
        ),
    ]


def norm(records, root):
    return compare.normalize_calls(records, [root])


def test_identical_logs_have_no_diff():
    a = norm(log("/sb1", "/tmp/w1"), "/sb1")
    assert compare.diff(a, a) == []


def test_only_sandbox_wrapper_and_partuuids_differ_reports_nothing():
    a = norm(log("/sb1", "/tmp/tmp.AAAA"), "/sb1")
    b = norm(log("/other/sb2", "/var/tmp/tmp.BBBB", UU_C, UU_D), "/other/sb2")
    assert compare.diff(a, b) == []


def test_a_run_of_lsusb_records_collapses_to_one_positioned_marker():
    recs = log("/sb1", "/tmp/w1")
    more = [dict(recs[0], argv=["-d", "0955:"]) for _ in range(3)]
    a = norm(more + recs, "/sb1")
    assert [r["tool"] for r in a] == ["lsusb", "sgdisk", "initrd-flash"]
    assert a == norm(recs, "/sb1")


def test_separated_lsusb_runs_stay_separate_markers():
    recs = log("/sb1", "/tmp/w1")
    spread = [recs[0], recs[1], dict(recs[0]), recs[2]]
    assert [r["tool"] for r in norm(spread, "/sb1")] == ["lsusb", "sgdisk", "lsusb", "initrd-flash"]


def test_a_missing_lsusb_run_is_reported():
    a = norm(log("/sb1", "/tmp/w1"), "/sb1")
    out = compare.diff(a, a[1:])
    assert out and "count" in out[0]


def test_engine_recheck_before_the_flash_is_removed_and_matches_the_oracle():
    oracle = log("/sb1", "/tmp/w1")
    engine = oracle[:2] + [dict(oracle[0])] + oracle[2:]
    assert compare.call_problems(oracle, engine, ["/sb1"], ["/sb1"]) == []


def test_engine_without_the_recheck_is_reported():
    oracle = log("/sb1", "/tmp/w1")
    problems = compare.call_problems(oracle, oracle, ["/sb1"], ["/sb1"])
    assert any("recheck" in p for p in problems)


def test_a_flash_free_engine_log_needs_no_recheck():
    oracle = log("/sb1", "/tmp/w1")[:2]
    assert compare.call_problems(oracle, oracle, ["/sb1"], ["/sb1"]) == []


def test_one_argument_differs_is_reported():
    a = norm(log("/sb1", "/tmp/w1"), "/sb1")
    b = norm(
        log(
            "/sb2",
            "/tmp/w2",
            flash_args=["--erase-nvme", "--erase-spi", "/sb2/imagez"],
        ),
        "/sb2",
    )
    out = compare.diff(a, b)
    assert len(out) == 1
    assert "initrd-flash" in out[0] and "argv" in out[0]
    assert out[0].startswith("call 2 ")  # index in the normalized log, lsusb run is one marker


def test_erase_flag_order_difference_is_reported():
    a = norm(log("/sb1", "/tmp/w1"), "/sb1")
    b = norm(
        log("/sb1", "/tmp/w1", flash_args=["--erase-spi", "--erase-nvme", "/sb1/images"]),
        "/sb1",
    )
    out = compare.diff(a, b)
    assert out and "initrd-flash" in out[0]


def test_call_count_difference_is_reported():
    a = norm(log("/sb1", "/tmp/w1"), "/sb1")
    out = compare.diff(a, a[:-1])
    assert out and "count" in out[0]


def test_tool_name_difference_is_reported():
    a = norm(log("/sb1", "/tmp/w1"), "/sb1")
    b = [a[0], dict(a[1], tool="sfdisk"), a[2]]
    out = compare.diff(a, b)
    assert out and "tool" in out[0]


def test_environment_difference_outside_partuuid_is_reported():
    a = norm(log("/sb1", "/tmp/w1"), "/sb1")
    recs = log("/sb1", "/tmp/w1")
    recs[2]["PYTHONWARNINGS"] = "default"
    b = norm(recs, "/sb1")
    out = compare.diff(a, b)
    assert out and "PYTHONWARNINGS" in out[0]


def test_non_flash_path_difference_is_reported():
    a = norm(log("/sb1", "/tmp/w1"), "/sb1")
    b = norm(log("/sb1", "/tmp/w1", path_tail="/opt/bin"), "/sb1")
    assert compare.diff(a, b)


# Built from named bits so the two modes differ only in the exec bit, which a
# comparer masking exec would miss, without a world-readable octal literal.
MODE_EXEC = stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR
MODE_PLAIN = stat.S_IRUSR | stat.S_IWUSR


def _make_layout(base: Path, uu_a: str, uu_b: str, extra: str = "") -> dict:
    (base / "sub").mkdir(parents=True)
    (base / "layout.xml").write_text(f"<p uuid='{uu_a}'/><q uuid='{uu_b}'/>{extra}")
    (base / "sub" / "f").write_text("data")
    os.chmod(base / "sub" / "f", MODE_EXEC)
    os.symlink("sub/f", base / "link")
    return {uu_a: "<PARTUUID-A>", uu_b: "<PARTUUID-B>"}


def test_snapshot_equal_when_only_partuuids_differ(tmp_path):
    m1 = _make_layout(tmp_path / "l", UU_A, UU_B)
    m2 = _make_layout(tmp_path / "r", UU_C, UU_D)
    s1 = compare.snapshot(tmp_path / "l", m1)
    s2 = compare.snapshot(tmp_path / "r", m2)
    assert s1 == s2
    assert compare.diff_snapshots(s1, s2) == []


def test_snapshot_records_type_mode_and_symlink_target(tmp_path):
    m = _make_layout(tmp_path / "l", UU_A, UU_B)
    s = compare.snapshot(tmp_path / "l", m)
    assert s["sub"][0] == "dir"
    assert s["sub/f"][0] == "file"
    assert s["sub/f"][1] == MODE_EXEC
    assert s["link"] == ("symlink", "sub/f")


def test_snapshot_detects_content_and_mode_difference(tmp_path):
    m1 = _make_layout(tmp_path / "l", UU_A, UU_B)
    m2 = _make_layout(tmp_path / "r", UU_C, UU_D, extra="<extra/>")
    out = compare.diff_snapshots(
        compare.snapshot(tmp_path / "l", m1), compare.snapshot(tmp_path / "r", m2)
    )
    assert out and "layout.xml" in out[0]
    os.chmod(tmp_path / "r" / "sub" / "f", MODE_PLAIN)
    m3 = {UU_C: "<PARTUUID-A>", UU_D: "<PARTUUID-B>"}
    s = compare.diff_snapshots(
        compare.snapshot(tmp_path / "l", m1), compare.snapshot(tmp_path / "r", m3)
    )
    assert any("sub/f" in line for line in s)


def test_deviation_registry_names():
    assert set(deviations.DEVIATIONS) == {
        "root-check-first",
        "absolute-cpp-wrapper",
        "unknown-profile-refused",
        "one-board-only",
        "carrier-values-literal",
        "boardctl-single-arguments",
        "prepare-only",
        "symlink-destination-replaced",
        "env-key-missing-refused",
        "carrier-label-optional",
        "mkbootimg-missing-refused",
        "env-file-missing-status",
        "tos-name-bare-filename",
        "layout-placeholder-unique",
        "build-dir-locked",
        "carrier-value-shell-safe",
        "recovery-pids-widened",
        "cmdline-control-chars-refused",
        "required-image-refused",
        "partition-fit-refused",
        "recovery-id-pinned",
        "device-confirmation",
    }
    assert all(isinstance(v, str) and v and "\n" not in v for v in deviations.DEVIATIONS.values())


ORACLE_WRAPPER = '#!/bin/bash\nexec cpp "$@"\n'
ENGINE_WRAPPER = '#!/bin/bash\nexec /opt/sdk/bin/x86_64-avocadosdk-linux-cpp "$@"\n'


def test_cpp_wrapper_rule_accepts_only_exec_target_difference():
    assert deviations.cpp_wrapper_equivalent(ORACLE_WRAPPER, ENGINE_WRAPPER)


def test_cpp_wrapper_rule_rejects_other_differences():
    assert not deviations.cpp_wrapper_equivalent(
        ORACLE_WRAPPER, ENGINE_WRAPPER.replace('"$@"', "")
    )
    assert not deviations.cpp_wrapper_equivalent(
        ORACLE_WRAPPER, ENGINE_WRAPPER.replace("#!/bin/bash", "#!/bin/sh")
    )
    assert not deviations.cpp_wrapper_equivalent(
        ORACLE_WRAPPER, ENGINE_WRAPPER + "echo extra\n"
    )


def pre_flash(tool, root, wrapper, stub="/stubs", system="/usr/bin"):
    return {
        "tool": tool,
        "argv": ["x"],
        "cwd": f"{root}/work",
        "PATH": f"{wrapper}:{root}/build/tegraflash:{stub}:{system}",
        "PYTHONWARNINGS": "ignore",
        "AVOCADO_KERNEL_CMDLINE_EXTRA": "",
    }


PRE = ("avocado-tegra-bootimg", "fdtput", "fdtget")


def test_wrapper_dir_masked_in_every_record_not_only_flash():
    a = norm([pre_flash(t, "/sb1", "/tmp/tmp.AbC123") for t in PRE], "/sb1")
    b = norm([pre_flash(t, "/sb2", "/tmp/tmpab12cd34") for t in PRE], "/sb2")
    assert compare.diff(a, b) == []
    assert all(r["PATH"].startswith("<WRAPPER_DIR>:") for r in a + b)


def test_other_path_element_difference_still_reported():
    a = norm([pre_flash("fdtput", "/sb1", "/tmp/tmp.A")], "/sb1")
    b = norm([pre_flash("fdtput", "/sb1", "/tmp/tmp.A", stub="/other")], "/sb1")
    assert compare.diff(a, b)
    c = norm([pre_flash("fdtput", "/sb1", "/tmp/tmp.A", system="/opt/bin")], "/sb1")
    assert compare.diff(a, c)


def test_missing_wrapper_element_on_one_side_is_reported():
    a = norm([pre_flash("fdtget", "/sb1", "/tmp/tmp.A")], "/sb1")
    rec_b = pre_flash("fdtget", "/sb1", "/tmp/tmp.A")
    rec_b["PATH"] = rec_b["PATH"].split(":", 1)[1]
    b = norm([rec_b], "/sb1")
    assert compare.diff(a, b)


def test_record_without_work_dir_element_is_left_alone():
    r = pre_flash("fdtget", "/sb1", "/tmp/tmp.A")
    r["PATH"] = "/tmp/tmp.A:/usr/bin"
    assert norm([r], "/sb1")[0]["PATH"] == "/tmp/tmp.A:/usr/bin"


def test_sandbox_roots_accept_path_objects():
    a = compare.normalize_calls([pre_flash("fdtget", "/sb1", "/tmp/w")], [Path("/sb1")])
    assert a[0]["cwd"] == "<SANDBOX>/work"
