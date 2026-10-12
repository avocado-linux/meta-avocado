"""ssh-emmc is dispatched before the script's parser, deploy and machine resolution."""

from __future__ import annotations

import sys

import pytest

from media_fixtures import load_avocado_flash, run_main_in_process


@pytest.fixture
def module(monkeypatch):
    mod = load_avocado_flash("avocado_flash_dispatch")

    def boom(*a, **k):
        raise AssertionError("resolve_deploy_dir must not run for ssh-emmc")

    monkeypatch.setattr(mod, "resolve_deploy_dir", boom)
    return mod


def test_ssh_emmc_reaches_stub_without_deploy_or_machine_lines(module, monkeypatch, tmp_path):
    result = run_main_in_process(module, ["ssh-emmc"], monkeypatch, tmp_path)
    assert result.exit == 64
    assert "valid subcommands: stage, check, plan, write, readback, restore, status" in result.stderr
    assert "machine:" not in result.stdout
    assert "deploy:" not in result.stdout


def test_ssh_emmc_flags_pass_through_intact(module, monkeypatch, tmp_path):
    from avocado_flash_remote import cli

    seen = []
    monkeypatch.setattr(cli, "main", lambda argv: seen.append(list(argv)) or 7)
    argv = ["--board", "x", "--images", "y", "--host", "z", "plan"]
    result = run_main_in_process(module, ["ssh-emmc", *argv], monkeypatch, tmp_path)
    assert seen == [argv]
    assert result.exit == 7


def test_existing_medium_does_not_touch_cli(module, monkeypatch, tmp_path):
    from avocado_flash_remote import cli

    monkeypatch.setattr(cli, "main", lambda argv: pytest.fail("cli reached"))
    result = run_main_in_process(module, ["bogus"], monkeypatch, tmp_path)
    assert result.exit == 2  # argparse rejection, unchanged


def test_ssh_emmc_not_first_argument_is_not_dispatched(module, monkeypatch, tmp_path):
    result = run_main_in_process(module, ["-n", "ssh-emmc"], monkeypatch, tmp_path)
    assert result.exit == 2  # argparse: invalid choice
    assert "invalid choice" in result.stderr
