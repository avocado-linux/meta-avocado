"""A followed write says which phase and image it is on, and that it is still alive (DVT-99.2)."""

from __future__ import annotations

from avocado_flash_remote import cli, host
from avocado_flash_remote import state as st
from avocado_flash_remote.cmd_status import run_status


class _Ctx:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def out(self, text: str) -> None:
        self.lines.append(text)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _rec(images: dict | None = None) -> host.Reconciled:
    return host.Reconciled(True, "image-writing", "r1", "restore-then-restart", "", images or {})


def _progress():
    ctx, clock = _Ctx(), _Clock()
    return ctx, clock, cli._WriteProgress(ctx, clock)


# --- the board's status answer names the images ------------------------------------------------------------


def _writing_run(state_dir):
    s = st.create_run(
        state_dir, run_id="r1", profile_hash="p", plan_hash="q",
        board_identity={}, image_roles=["rootfs", "var"], arm=True,
    )  # fmt: skip
    s = st.transition(s, "table-writing")
    s = st.transition(s, "table-written")
    return st.transition(s, "image-writing", image="rootfs")


def test_status_names_each_image_and_its_state_on_a_second_line(tmp_path):
    _writing_run(tmp_path)
    lines = []
    res = run_status(tmp_path, out=lines.append)
    assert res.phase == "image-writing"
    assert lines[0].startswith("status: image-writing run=r1 recovery=")
    assert lines[1] == "images: rootfs=writing, var=pending"


def test_status_with_no_images_keeps_its_single_line(tmp_path):
    st.create_run(
        tmp_path, run_id="r1", profile_hash="p", plan_hash="q",
        board_identity={}, image_roles=[], arm=True,
    )  # fmt: skip
    lines = []
    run_status(tmp_path, out=lines.append)
    assert len(lines) == 1 and lines[0].startswith("status: planned")


def test_the_host_reads_the_images_line_and_ignores_a_board_that_sends_none():
    text = "status: image-writing run=r1 recovery=x\nimages: rootfs=written, var=writing"
    assert host._parse_images(text) == {"rootfs": "written", "var": "writing"}
    assert host._parse_images("status: planned run=r1 recovery=x") == {}


# --- what the host prints while it follows ------------------------------------------------------------------


def test_a_new_phase_prints_a_line_naming_the_images():
    ctx, clock, progress = _progress()
    progress.poll(_rec({"rootfs": "writing", "var": "pending"}), "image-writing")
    assert ctx.lines == ["write: image-writing - images: rootfs=writing, var=pending"]


def test_an_image_changing_state_prints_a_line_with_the_phase_unchanged():
    ctx, clock, progress = _progress()
    progress.poll(_rec({"rootfs": "writing", "var": "pending"}), "image-writing")
    clock.now += 5
    progress.poll(_rec({"rootfs": "written", "var": "writing"}), "image-writing")
    assert ctx.lines[-1] == "write: image-writing - images: rootfs=written, var=writing"
    assert len(ctx.lines) == 2


def test_an_unchanged_record_is_silent_until_ten_seconds_then_a_heartbeat_with_the_elapsed_time():
    ctx, clock, progress = _progress()
    rec = _rec({"rootfs": "writing"})
    progress.poll(rec, "image-writing")
    clock.now += 4
    progress.poll(rec, "image-writing")
    assert len(ctx.lines) == 1
    clock.now += 7
    progress.poll(rec, "image-writing")
    assert ctx.lines[-1] == "write: still image-writing, 11 s - images: rootfs=writing"


def test_a_heartbeat_repeats_every_ten_seconds_of_continued_silence():
    ctx, clock, progress = _progress()
    rec = _rec()
    progress.poll(rec, "image-writing")
    for _ in range(4):
        clock.now += 5
        progress.poll(rec, "image-writing")
    assert [line.split(",")[0] for line in ctx.lines[1:]] == ["write: still image-writing", "write: still image-writing"]


def test_a_dropped_poll_keeps_the_last_known_phase_instead_of_claiming_the_board_has_no_record():
    ctx, clock, progress = _progress()
    progress.poll(_rec({"rootfs": "writing"}), "image-writing")
    clock.now += 12
    progress.poll(None, None)  # the ssh poll dropped: no record, no phase
    assert ctx.lines[-1] == "write: still image-writing, 12 s - images: rootfs=writing"


def test_no_recorded_phase_yet_is_a_heartbeat_not_a_phase_line():
    ctx, clock, progress = _progress()
    progress.poll(host.Reconciled(True), None)
    assert ctx.lines == []
    clock.now += 10
    progress.poll(host.Reconciled(True), None)
    assert ctx.lines == ["write: still waiting for the board to record the run, 10 s"]
