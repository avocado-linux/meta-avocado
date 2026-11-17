"""Differential proof: the engine behaves like the frozen legacy script.

Every planned case (profile entries and failure variants) runs through the
oracle and the engine in separate work directories. Exit statuses must be
equal, the normalized call logs must match, and the work-directory snapshots
(after the PARTUUID mapping) must match.

A case whose oracle cannot run (no jq) counts as not run, never as passed.
The last test in this file compares the number of compared cases against the
number planned, so it fails by design when any case did not run, including
under `-k`, `-x`, xdist or `pytest test_parity.py::test_parity[one-id]`
selection. Run the whole file to get a meaningful verdict.
"""

from __future__ import annotations

import pytest

from parity import cases, compare, runner

PLANNED = cases.all_cases()

# Filled by test_parity, read by test_all_planned_cases_ran. Test order is file
# order, so the parametrized cases run before the count check.
_RAN: list[str] = []
_NOT_RUN: dict[str, str] = {}


def _roots(*workdirs):
    # normalize_calls sorts the roots by len(), so pass strings, not Paths.
    return [str(w) for w in workdirs]


def _snapshot(result, workdir):
    """Re-take the work directory snapshot with the sandbox root mapped too.

    The recording initrd-flash stub the fixtures write into the work directory
    embeds the side's own log and scenario paths, so the snapshot the runner
    returns differs between sides by environment alone. The mapping adds only
    that root to the PARTUUID placeholders.
    """
    mapping = compare.extract_partuuids(result.calls)
    mapping[str(workdir)] = "<SANDBOX>"
    return compare.snapshot(workdir / "tree" / "build" / "tegraflash", mapping)


_PAIRS: dict = {}
_ENGINE_WORKDIR: dict = {}


def run_pair(case, tmp_path):
    """Run both sides and return (oracle, engine, problems).

    problems holds every difference between the two runs plus anything either
    side did that the comparison must never allow: a program started that no
    stub intercepts, or a change outside the work directory. A case is run once
    per session: the dedicated deviation tests read the result test_parity
    already produced instead of running the oracle again.
    """
    if case.id not in _PAIRS:
        _PAIRS[case.id] = _run_pair(case, tmp_path)
    return _PAIRS[case.id]


def _run_pair(case, tmp_path):
    w_oracle = tmp_path / "oracle"
    w_engine = tmp_path / "engine"
    _ENGINE_WORKDIR[case.id] = w_engine
    oracle = runner.run_oracle(case, w_oracle)
    engine = runner.run_engine(case, w_engine)
    problems = []
    if oracle.exit_status != engine.exit_status:
        problems.append(f"exit status differs: oracle {oracle.exit_status} vs engine {engine.exit_status}")
    problems += compare.call_problems(oracle.calls, engine.calls, _roots(w_oracle), _roots(w_engine))
    problems += [
        f"snapshot: {p}"
        for p in compare.diff_snapshots(_snapshot(oracle, w_oracle), _snapshot(engine, w_engine))
    ]
    for side, result in (("oracle", oracle), ("engine", engine)):
        problems += [f"{side} started an unstubbed program: {name}" for name in result.unstubbed]
        problems += [f"{side} changed a path outside the work directory: {c}" for c in result.outside_changes]
    return oracle, engine, problems


# What a listed deviation is allowed to change, as substrings of a problem line.
# Every substring must show in the case's problems (the deviation is observed),
# and nothing else may. None means the oracle aborts early, so the whole diff
# is the deviation and the dedicated test below pins the observable instead.
DEVIATION_EFFECTS = {
    "symlink-destination-replaced": (
        "snapshot: shadow-link",
        "oracle changed a path outside the work directory: outside/sentinel.txt",
    ),
    "env-file-missing-status": ("exit status differs: oracle 2 vs engine 1",),
    "carrier-label-optional": None,
}

# Deviations where the engine refuses a case the oracle carries out: the oracle's
# side of the diff is the deviation, so only the engine's behaviour is pinned.
ENGINE_REFUSES = {"tos-name-bare-filename"}


def _tools(result):
    return [c["tool"] for c in result.calls]


def _fdtput_values(result):
    return [c["argv"][-1] for c in result.calls if c["tool"] == "fdtput"]


def _deviation_cases(name):
    return [c for c in PLANNED if c.deviation == name]


def engine_findings(result):
    """What the engine run must never do, whatever a listed deviation allows."""
    return [f"engine started an unstubbed program: {n}" for n in result.unstubbed] + [
        f"engine changed a path outside the work directory: {c}" for c in result.outside_changes
    ]


def _engine_calls(case, tmp_path):
    _oracle, engine, _problems = run_pair(case, tmp_path)
    return compare.normalize_calls(engine.calls, _roots(_ENGINE_WORKDIR[case.id]))


def _aborting_deviation_problems(case, tmp_path):
    """The oracle aborts early, so its side of the diff is the deviation. The
    engine side is still held to the checks of any other case: nothing unstubbed,
    nothing outside the work directory, and the same calls as the case without
    the deviation (here the base carrier case), since only the oracle differs."""
    oracle, engine, problems = run_pair(case, tmp_path)
    found = [] if problems else [f"the deviation {case.deviation} showed no difference"]
    found += engine_findings(engine)
    found += [f"oracle started an unstubbed program: {n}" for n in oracle.unstubbed]
    base = next(c for c in PLANNED if c.id == case.id.rsplit("/", 1)[0] + "/carrier")
    if _engine_calls(case, tmp_path) != _engine_calls(base, tmp_path / "base"):
        found.append("engine calls differ from the base carrier case")
    return found


@pytest.mark.parametrize("case", PLANNED, ids=[c.id for c in PLANNED])
def test_parity(case, tmp_path):
    try:
        _oracle, _engine, problems = run_pair(case, tmp_path)
    except runner.OracleUnavailable as exc:
        _NOT_RUN[case.id] = str(exc)
        pytest.fail(f"NOT RUN: {exc}")
    # Compared, whatever the verdict: a difference fails this case, not the count.
    _RAN.append(case.id)
    if case.deviation in ENGINE_REFUSES:
        problems = engine_findings(_engine)
    elif case.deviation:
        effects = DEVIATION_EFFECTS[case.deviation]
        if effects is None:
            problems = _aborting_deviation_problems(case, tmp_path)
        else:
            problems = [p for p in problems if not any(e in p for e in effects)]
    assert not problems, f"{case.id}: {len(problems)} difference(s)\n" + "\n".join(problems)


def _assert_effects_observed(case, problems):
    for effect in DEVIATION_EFFECTS[case.deviation]:
        assert any(effect in p for p in problems), f"{case.deviation}: no problem mentions {effect!r}: {problems}"


@pytest.mark.deviation("symlink-destination-replaced")
@pytest.mark.parametrize("case", _deviation_cases("symlink-destination-replaced"), ids=lambda c: c.id)
def test_symlink_destination_is_replaced_by_the_engine_and_written_through_by_the_oracle(case, tmp_path):
    _oracle, _engine, problems = run_pair(case, tmp_path)
    _assert_effects_observed(case, problems)
    assert not any("engine changed a path outside" in p for p in problems), problems


@pytest.mark.deviation("tos-name-bare-filename")
@pytest.mark.parametrize("case", _deviation_cases("tos-name-bare-filename"), ids=lambda c: c.id)
def test_absolute_tos_name_is_used_by_the_oracle_and_refused_by_the_engine(case, tmp_path):
    oracle, engine, _problems = run_pair(case, tmp_path)
    assert oracle.exit_status == 0 and "initrd-flash" in _tools(oracle)
    assert engine.exit_status == 1 and not {"initrd-flash", "lsusb", "boardctl"} & set(_tools(engine))
    assert engine_findings(engine) == []


@pytest.mark.deviation("carrier-label-optional")
@pytest.mark.parametrize("case", _deviation_cases("carrier-label-optional"), ids=lambda c: c.id)
def test_carrier_env_without_a_label_aborts_the_oracle_and_the_engine_proceeds(case, tmp_path):
    oracle, engine, _problems = run_pair(case, tmp_path)
    assert oracle.exit_status != 0 and "initrd-flash" not in _tools(oracle)
    assert engine.exit_status == 0 and "initrd-flash" in _tools(engine)


@pytest.mark.parametrize("case", [c for c in PLANNED if c.id.endswith("/priority-trailing-comma")], ids=lambda c: c.id)
def test_stock_priority_ending_in_a_comma_is_written_like_the_oracle(case, tmp_path):
    oracle, engine, problems = run_pair(case, tmp_path)
    assert problems == []
    (written,) = _fdtput_values(oracle)
    assert not written.endswith(",")
    assert _fdtput_values(engine) == [written]


@pytest.mark.deviation("env-file-missing-status")
@pytest.mark.parametrize("case", _deviation_cases("env-file-missing-status"), ids=lambda c: c.id)
def test_bsp_without_the_env_file_exits_1_in_the_engine_and_2_in_the_oracle(case, tmp_path):
    oracle, engine, problems = run_pair(case, tmp_path)
    _assert_effects_observed(case, problems)
    assert (oracle.exit_status, engine.exit_status) == (2, 1)


@pytest.mark.parametrize("case", [c for c in PLANNED if c.id.endswith("/no-board")], ids=lambda c: c.id)
def test_no_board_refuses_on_both_sides_and_never_flashes(case, tmp_path):
    oracle, engine, problems = run_pair(case, tmp_path)
    assert problems == []
    assert oracle.exit_status != 0 and engine.exit_status != 0
    for result in (oracle, engine):
        assert "initrd-flash" not in [c["tool"] for c in result.calls]


def test_all_planned_cases_ran():
    planned = len(PLANNED)
    ran = len(set(_RAN))
    print(cases.report(ran, planned))
    assert not cases.shortfall(ran, planned), (
        f"{cases.report(ran, planned)}; not run for lack of the oracle: {sorted(_NOT_RUN)}"
    )
    assert not _NOT_RUN
