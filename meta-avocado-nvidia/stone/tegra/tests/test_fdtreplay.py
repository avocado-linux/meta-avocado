import shutil
import subprocess
from pathlib import Path

import pytest

from avocado_tegraflash import EngineError
from avocado_tegraflash.fdtreplay import integrator_set, read_tree, replay
from avocado_tegraflash.runner import SubprocessRunner

PACKAGE_HINT = "install the device-tree-compiler package (dtc, fdtoverlay)"

BASE = """/dts-v1/;
/ {
    compatible = "test,board";
    camera {
        channels = <%d>;
        label = "cam";
        extra = <1 2>;
    };
};
"""

OVERLAY = """/dts-v1/;
/plugin/;
/ {
    fragment@0 {
        target-path = "/camera";
        __overlay__ {
            %s
        };
    };
};
"""


@pytest.fixture(autouse=True)
def _require_dtc():
    # A missing tool must fail the suite, not skip it: a skip would let CI go green without testing the replay.
    for tool in ("dtc", "fdtoverlay"):
        if shutil.which(tool) is None:
            pytest.fail(f"{tool} not found on PATH: {PACKAGE_HINT}")


def compile_dts(tmp_path, name, text, *, overlay=False):
    src = tmp_path / f"{name}.dts"
    src.write_text(text)
    out = tmp_path / f"{name}.dtb"
    argv = ["dtc", "-q", "-I", "dts", "-O", "dtb"]
    if overlay:
        argv.append("-@")
    subprocess.run([*argv, "-o", str(out), str(src)], check=True)
    return out


def base_tree(tmp_path, name, channels):
    return compile_dts(tmp_path, name, BASE % channels)


def overlay_file(tmp_path, name, body, **kw):
    return compile_dts(tmp_path, name, OVERLAY % body, overlay=True, **kw)


class CountingRunner:
    def __init__(self):
        self.calls = []

    def run(self, argv, *, cwd=None, env=None):
        self.calls.append(list(argv))
        return 0

    def capture(self, argv, *, cwd=None, env=None, discard_stderr=False, timeout=None):
        self.calls.append(list(argv))
        return 0, ""


def test_read_tree_returns_node_paths_and_property_bytes(tmp_path):
    tree = read_tree(base_tree(tmp_path, "t", 52))

    assert tree["/"]["compatible"] == b"test,board\x00"
    assert tree["/camera"]["channels"] == (52).to_bytes(4, "big")
    assert tree["/camera"]["label"] == b"cam\x00"


def test_read_tree_refuses_a_file_that_is_not_a_tree(tmp_path):
    bogus = tmp_path / "bogus.dtb"
    bogus.write_bytes(b"not a device tree at all, just text padding.....")

    with pytest.raises(EngineError, match="bogus.dtb"):
        read_tree(bogus)


def test_read_tree_refuses_a_truncated_tree(tmp_path):
    good = base_tree(tmp_path, "t", 52).read_bytes()
    cut = tmp_path / "cut.dtb"
    cut.write_bytes(good[: len(good) // 2])

    with pytest.raises(EngineError, match="cut.dtb"):
        read_tree(cut)


def test_integrator_set_holds_changed_and_added_properties_only():
    stock = {"/": {"a": b"1"}, "/n": {"x": b"1", "y": b"2"}}
    flashed = {"/": {"a": b"1"}, "/n": {"x": b"9", "y": b"2", "z": b"3"}, "/m": {"q": b"1"}}

    assert integrator_set(stock, flashed) == {
        ("/n", "x"): b"9",
        ("/n", "z"): b"3",
        ("/m", "q"): b"1",
    }


def test_integrator_set_ignores_symbol_and_fixup_nodes():
    stock = {"/": {}}
    flashed = {
        "/": {},
        "/__symbols__": {"a": b"/x\x00"},
        "/__fixups__": {"a": b"/x\x00"},
        "/__local_fixups__": {"a": b"\x00"},
    }

    assert integrator_set(stock, flashed) == {}


def test_channel_count_reset_by_an_overlay_is_reported_with_both_values(tmp_path):
    stock = base_tree(tmp_path, "stock", 8)
    flashed = base_tree(tmp_path, "flashed", 52)
    reset = overlay_file(tmp_path, "camera-reset", "channels = <2>;")

    result = replay(flashed, [reset], SubprocessRunner(), tmp_path / "scratch", stock_path=stock)

    assert [(c.path, c.property, c.before, c.after, c.overlay) for c in result.changes] == [
        ("/camera", "channels", "0x00000034", "0x00000002", "camera-reset.dtb")
    ]
    assert result.failures == []
    assert result.skipped is None


def test_change_made_by_the_last_overlay_in_the_chain_is_reported(tmp_path):
    stock = base_tree(tmp_path, "stock", 8)
    flashed = base_tree(tmp_path, "flashed", 52)
    harmless = overlay_file(tmp_path, "first", 'other = "x";')
    last = overlay_file(tmp_path, "last", "channels = <2>;")

    result = replay(flashed, [harmless, last], SubprocessRunner(), tmp_path / "scratch", stock_path=stock)

    assert [c.overlay for c in result.changes] == ["last.dtb"]


def test_identical_trees_make_no_runner_call(tmp_path):
    stock = base_tree(tmp_path, "stock", 52)
    flashed = tmp_path / "flashed.dtb"
    flashed.write_bytes(stock.read_bytes())
    overlay = overlay_file(tmp_path, "o", "channels = <2>;")
    runner = CountingRunner()

    result = replay(flashed, [overlay], runner, tmp_path / "scratch", stock_path=stock)

    assert runner.calls == []
    assert result.no_integrator_properties is True
    assert result.changes == []


def test_failing_overlay_is_recorded_and_the_next_one_still_applies(tmp_path):
    stock = base_tree(tmp_path, "stock", 8)
    flashed = base_tree(tmp_path, "flashed", 52)
    broken = compile_dts(
        tmp_path,
        "broken",
        '/dts-v1/;\n/plugin/;\n/ { fragment@0 { target-path = "/nowhere"; __overlay__ { a = <1>; }; }; };\n',
        overlay=True,
    )
    good = overlay_file(tmp_path, "good", "channels = <2>;")

    result = replay(flashed, [broken, good], SubprocessRunner(), tmp_path / "scratch", stock_path=stock)

    assert [f.overlay for f in result.failures] == ["broken.dtb"]
    assert result.failures[0].status != 0
    assert [c.overlay for c in result.changes] == ["good.dtb"]


def test_removed_property_is_reported_as_disappeared(tmp_path):
    stock = compile_dts(tmp_path, "stock", BASE.replace("extra = <1 2>;", "") % 8)
    flashed = base_tree(tmp_path, "flashed", 8)
    remove = overlay_file(tmp_path, "remove", "channels = <8>;")

    class DroppingRunner(CountingRunner):
        # fdtoverlay only merges and cannot delete a property, so a tool whose output lacks one stands in for it.
        def capture(self, argv, **kw):
            shutil.copyfile(stock, argv[argv.index("-o") + 1])
            return 0, ""

    result = replay(flashed, [remove], DroppingRunner(), tmp_path / "scratch", stock_path=stock)

    assert [(c.path, c.property, c.before, c.after) for c in result.changes] == [
        ("/camera", "extra", "0x00000001 0x00000002", None)
    ]


def test_string_values_format_as_text(tmp_path):
    stock = base_tree(tmp_path, "stock", 8)
    flashed = compile_dts(tmp_path, "flashed", (BASE % 8).replace('"cam"', '"cam2"'))
    relabel = overlay_file(tmp_path, "relabel", 'label = "cam3";')

    result = replay(flashed, [relabel], SubprocessRunner(), tmp_path / "scratch", stock_path=stock)

    assert [(c.property, c.before, c.after) for c in result.changes] == [("label", "cam2", "cam3")]


def test_input_tree_is_not_modified(tmp_path):
    stock = base_tree(tmp_path, "stock", 8)
    flashed = base_tree(tmp_path, "flashed", 52)
    before = flashed.read_bytes()
    overlay = overlay_file(tmp_path, "o", "channels = <2>;")

    replay(flashed, [overlay], SubprocessRunner(), tmp_path / "scratch", stock_path=stock)

    assert flashed.read_bytes() == before


def test_missing_fdtoverlay_marks_the_result_skipped(tmp_path, monkeypatch):
    stock = base_tree(tmp_path, "stock", 8)
    flashed = base_tree(tmp_path, "flashed", 52)
    overlay = overlay_file(tmp_path, "o", "channels = <2>;")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    runner = CountingRunner()

    result = replay(flashed, [overlay], runner, tmp_path / "scratch", stock_path=stock)

    assert "fdtoverlay" in result.skipped
    assert runner.calls == []


def test_runner_is_called_with_argv_list_and_timeout(tmp_path):
    stock = base_tree(tmp_path, "stock", 8)
    flashed = base_tree(tmp_path, "flashed", 52)
    overlay = overlay_file(tmp_path, "o", "channels = <2>;")
    seen = []

    class Spy(SubprocessRunner):
        def capture(self, argv, **kw):
            seen.append((list(argv), kw.get("timeout")))
            return super().capture(argv, **kw)

    replay(flashed, [overlay], Spy(), tmp_path / "scratch", stock_path=stock)

    argv, timeout = seen[0]
    assert Path(argv[0]).name == "fdtoverlay"
    assert argv[1] == "-i" and argv[3] == "-o" and argv[5] == str(overlay)
    assert argv[2] != str(flashed)
    assert timeout and timeout > 0
