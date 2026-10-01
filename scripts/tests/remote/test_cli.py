"""Readback command-line gating by arm strategy (task 5.13). Stub transport only."""

from __future__ import annotations

import pytest

from test_cli_lifecycle import Board, args, images, run  # noqa: F401  (fixtures)


@pytest.fixture
def board(tmp_path):
    return Board(tmp_path)


def _stage(images, tmp_path, board):
    assert run(args(images, tmp_path, "stage"), board)[0] == 0


def _readback_req(board):
    return next(r for s, r, _ in board.runs if s == "readback")


def test_arm_none_readback_needs_no_reference(images, tmp_path, board):
    _stage(images, tmp_path, board)
    rc, text = run(args(images, tmp_path, "readback"), board)
    assert rc == 0
    assert "readback" in board.subs()
    assert "reference_boot_order" not in _readback_req(board)
    assert "ignored" not in text


def test_arm_none_reference_is_accepted_and_ignored_with_one_line(images, tmp_path, board):
    _stage(images, tmp_path, board)
    rc, text = run(args(images, tmp_path, "readback", "--reference-boot-order", "0001"), board)
    assert rc == 0
    assert text.count("--reference-boot-order ignored (arm strategy none)") == 1
    assert "reference_boot_order" not in _readback_req(board)


def test_arm_uefi_without_reference_still_exits_64(images, tmp_path, capsys):
    rc, _ = run(args(images, tmp_path, "readback") + ["--board", "jetson-agx-orin-j5012"])
    assert rc == 64
    assert "--reference-boot-order" in capsys.readouterr().err
