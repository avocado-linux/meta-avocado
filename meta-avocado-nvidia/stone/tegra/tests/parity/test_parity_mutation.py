"""The parity comparison must notice a broken engine.

A green parity run proves little unless the comparison can fail. Each test
mutates a temporary copy of the engine (never the real package) and checks that
the same comparison test_parity.py applies reports a difference naming the
expected call. The unmutated engine on the same case is the control: it must
compare clean, so a difference cannot come from a harness that always reports
one.

The recovery stage is covered too: an engine that never waits for the board, or
never rechecks it right before the flash, must fail the comparison even though
the number of lsusb polls is not compared.

An oracle that cannot run (no jq) raises OracleUnavailable; it is not caught
here, so such a run errors instead of passing.
"""

from __future__ import annotations

import dataclasses

import pytest

from parity import cases, compare, runner, test_parity

_NO_WAIT = (
    'board = __import__("types").SimpleNamespace(bus="001", device="005", vid="0955", pid="7523") '
    "if True else recovery.wait_for_single_board(\n"
)

# (id, file in the package, exact text, replacement, text a reported difference must contain)
MUTATIONS = [
    (
        "erase-flag-order",
        "flash.py",
        "    return sorted(found)\n",
        "    return sorted(found, reverse=True)\n",
        "initrd-flash",
    ),
    (
        "nvme-default-dropped",
        "flash.py",
        "    if media is Media.NVME or erase_nvme:\n",
        "    if erase_nvme:\n",
        "initrd-flash",
    ),
]

# Recovery-stage mutations, each run on the base case and on the third-poll case.
RECOVERY_MUTATIONS = [
    (
        "recheck-removed",
        "cli.py",
        "    recovery.recheck_single_board(runner, flash_env, board, expected_ids=man.rcm_ids)\n",
        "    pass\n",
        "recheck",
    ),
    (
        "wait-removed",
        "cli.py",
        "        board = recovery.wait_for_single_board(\n",
        "        " + _NO_WAIT,
        "lsusb",
    ),
]


def _erase_case():
    base = _base_case()
    env = {**base.env_dict, "ERASE_EMMC": "1", "ERASE_ONLY": "1"}
    return dataclasses.replace(base, id=base.id + "-erase-mutation", env=tuple(sorted(env.items())))


def _base_case():
    return next(
        c
        for c in cases.all_cases()
        if c.manifest.stem == "stone-jetson-orin-nano"
        and c.profile == "tegraflash-nvme"
        and c.id.endswith("/base")
    )


def _third_poll_case():
    return next(
        c
        for c in cases.all_cases()
        if c.manifest.stem == "stone-jetson-orin-nano" and c.id.endswith("/third-poll")
    )


def _differences(case, tmp_path, engine_root=None):
    w_oracle = tmp_path / "oracle"
    w_engine = tmp_path / "engine"
    oracle = runner.run_oracle(case, w_oracle)
    engine = runner.run_engine(case, w_engine, engine_root=engine_root)
    problems = []
    if oracle.exit_status != engine.exit_status:
        problems.append(f"exit status differs: oracle {oracle.exit_status} vs engine {engine.exit_status}")
    problems += compare.call_problems(oracle.calls, engine.calls, [str(w_oracle)], [str(w_engine)])
    return problems


def test_unmutated_engine_compares_clean_on_the_erase_case(tmp_path):
    assert _differences(_erase_case(), tmp_path) == []


@pytest.mark.parametrize("mutation", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_parity_comparison_detects_a_mutated_engine(mutation, mutated_root, tmp_path):
    _id, filename, old, new, needle = mutation
    root = mutated_root(filename, old, new)
    problems = _differences(_erase_case(), tmp_path / "run", engine_root=root)
    assert problems, "the comparison reported no difference for a mutated engine"
    assert any(needle in p for p in problems), problems


@pytest.mark.parametrize("make_case", [_base_case, _third_poll_case], ids=["base", "third-poll"])
def test_unmutated_engine_compares_clean_on_the_recovery_cases(make_case, tmp_path):
    assert _differences(make_case(), tmp_path) == []


@pytest.mark.parametrize("make_case", [_base_case, _third_poll_case], ids=["base", "third-poll"])
@pytest.mark.parametrize("mutation", RECOVERY_MUTATIONS, ids=[m[0] for m in RECOVERY_MUTATIONS])
def test_parity_comparison_detects_an_engine_without_the_recovery_stage(mutation, make_case, mutated_root, tmp_path):
    _id, filename, old, new, needle = mutation
    root = mutated_root(filename, old, new)
    problems = _differences(make_case(), tmp_path / "run", engine_root=root)
    assert any(needle in p for p in problems), problems


def test_an_engine_starting_an_unstubbed_program_fails_the_aborting_deviation_case(mutated_root, tmp_path):
    # carrier-label-optional is the case whose oracle side is not compared, so the
    # engine side must still be held to the unstubbed-program check.
    case = next(c for c in cases.all_cases() if c.deviation == "carrier-label-optional")
    root = mutated_root(
        "bootpriority.py",
        '["fdtget", "-t", "s", str(dtbo), NODE, "data"]',
        '["nosuchtool", "-t", "s", str(dtbo), NODE, "data"]',
    )
    result = runner.run_engine(case, tmp_path / "run", engine_root=root)
    assert test_parity.engine_findings(result) == ["engine started an unstubbed program: nosuchtool"]
    clean = runner.run_engine(case, tmp_path / "clean")
    assert test_parity.engine_findings(clean) == []


def test_mutation_anchor_that_matches_nowhere_is_refused(mutated_root):
    with pytest.raises(AssertionError, match="matches 0 places"):
        mutated_root("flash.py", "no such text in flash.py", "x")
