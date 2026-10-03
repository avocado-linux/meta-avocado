"""The README is written from the code: names it documents must exist in the code."""

import pathlib
import re
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from avocado_flash_remote import host, state  # noqa: E402

README = (SCRIPTS / "avocado_flash_remote" / "README.md").read_text()


def _section(title):
    m = re.search(rf"^#+ {re.escape(title)}[^\n]*\n(.*?)(?=^#+ |\Z)", README, re.S | re.M)
    assert m, f"README has no section {title!r}"
    return m.group(1)


def _table_first_cells(text):
    return {m.group(1) for m in re.finditer(r"^\| `([^`]+)` \|", text, re.M)}


def test_every_phase_has_a_row_in_the_recovery_table():
    rows = _table_first_cells(_section("Run state and recovery"))
    missing = [p for p in state.PHASES if p not in rows]
    assert not missing, f"phases missing from the README recovery table: {missing}"


def test_phase_order_line_names_every_phase():
    text = _section("Run state and recovery")
    missing = [p for p in state.PHASES if f"`{p}`" not in text]
    assert not missing


def test_every_recovery_action_is_named():
    text = _section("Run state and recovery")
    missing = [a for a in set(state.RECOVERY.values()) if f"`{a}`" not in text]
    assert not missing, missing


def test_accepted_marker_is_documented_by_its_code_name():
    assert host.ACCEPTED_MARKER == "accepted"
    assert f"`{host.ACCEPTED_MARKER}`" in README


def test_exit_2_meaning_covers_connection_drop_for_the_four_subcommands():
    text = _section("Exit codes")
    assert "connection" in text and "dropped" in text
    for sub in ("check", "status", "readback", "restore"):
        assert f"`{sub}`" in text, sub


def test_extension_pinning_instructions():
    text = _section("Pinning the eMMC serial")
    for needle in ("--extension-dir", "serial", "sysfs_attr", "target-identity", "checks", "0x0badc0de"):
        assert needle in text, needle


def test_readme_has_no_em_or_en_dashes():
    assert "—" not in README and "–" not in README


def test_readme_has_a_recovery_section_naming_the_manual_wipe_and_restage():
    text = _section("Starting over after a failed write")
    for needle in ("require_empty", "wipefs", "stage", "restore", "identity"):
        assert needle in text, needle


def test_readme_documents_the_emergency_disarm_lock_wait():
    text = _section("Restore scope")
    # The manual steps used to include `efibootmgr -B -b XXXX`; the tool deletes no entry now (task 5.36).
    assert "emergency-disarm" in text and "waits" in text and "efibootmgr -N" in text
    assert "efibootmgr -B" not in text


def test_readme_documents_the_firmware_entry_arm():
    flat = _flat(README)
    for needle in ("entry_label", "UEFI eMMC Device", "arm-entry-unique", "efibootmgr -n <entry>",
                   "no longer passes `bootmode=bootimg`", "deletes no boot entry"):
        assert needle in flat, needle
    for gone in ("loader_path", "boot_args", "no-stale-oneshot-entry", "efibootmgr -C` and sets"):
        assert gone not in flat, gone


def test_readme_documents_the_outcome_marker():
    assert "`outcome`" in README and "`refused`" in README


def _flat(text):
    return re.sub(r"\s+", " ", text)


def test_readme_markers_are_deleted_only_for_an_accepted_invocation():
    flat = _flat(README)
    assert "only for an accepted invocation" in flat
    assert "at the start of every invocation the runner" not in flat
    assert "A refused invocation (a replay, a held lock, a bad nonce) deletes and writes no marker" in flat


def test_readme_says_did_not_write_it_never_goes_with_an_unknown():
    flat = _flat(README)
    assert 'it never says "did not write it" for an unknown' in flat
    assert 'could not confirm which invocation wrote the run' in flat


def test_readme_refusal_phrases_match_the_runner():
    from avocado_flash_remote import runner

    src = _flat(pathlib.Path(runner.__file__).read_text())
    for phrase in ("already in progress, a runner holds this run", "the board may be changing"):
        assert phrase in src
        assert phrase in _flat(README)


def test_readme_names_the_per_invocation_request_file_and_the_status_run_id():
    flat = _flat(README)
    assert "request-write-<nonce>.json" in flat
    assert "asks `status` for its own run id" in flat


def test_readme_emergency_disarm_decides_on_the_holder_pid_not_the_phase():
    flat = _flat(_section("Restore scope"))
    assert "whose pid is gone" in flat and "/proc" in flat
    assert "A live holder" in flat and "no manual commands" in flat


def test_board_prerequisites_section_names_every_tool_and_the_busybox_limit():
    text = _section("Board prerequisites")
    for needle in ("install -d", "sha256sum --strict", "dd conv=fsync", "status=none", "Python 3", "board-prerequisites", "busybox"):
        assert needle in text, needle


def _flat_text(text):
    return " ".join(text.split())


def test_board_prerequisites_says_the_module_check_is_the_hosts_interpreter_probe():
    flat = _flat_text(_section("Board prerequisites"))
    assert "module check is the host's interpreter probe" in flat
    assert "imports each standard-library module" not in flat
    assert "or module" not in flat


def test_board_prerequisites_says_the_tool_banner_must_name_gnu_coreutils():
    flat = _flat_text(_section("Board prerequisites"))
    assert "GNU coreutils" in flat and "toybox" in flat and "uutils" in flat


def test_the_known_limit_for_busybox_no_longer_claims_a_python_check():
    row = next(ln for ln in _section("Known limits").splitlines() if ln.startswith("| Busybox portability"))
    assert "standard library" not in row


def test_the_write_row_and_the_parity_section_record_the_read_back_cache_flush():
    assert "blockdev --flushbufs" in _flat_text(_section("Subcommands and their gates"))
    flat = _flat_text(_section("The one-shot boot and its limits"))
    assert "D11" in flat and "blockdev --flushbufs" in flat
    assert "readback_after_cache_flush" in _flat_text(_section("Run state and recovery"))


def test_the_runner_takes_state_dir_from_the_profile_not_the_request():
    flat = _flat_text(_section("Schema version 1"))
    assert "the runner ignores a state directory in a request" in flat


def test_the_preflight_check_list_names_board_prerequisites():
    assert "`board-prerequisites`" in _section("Schema version 1")


def test_known_limits_count_matches_the_debt_markers_in_the_code():
    import test_debt_markers as dm

    words = {6: "Six", 7: "Seven"}
    found = len(list(dm.markers()))
    text = _section("Known limits")
    assert f"{words[found]} debts were found" in text
    rows = [ln for ln in text.splitlines() if ln.startswith("| ") and not ln.startswith(("| Limit", "|---"))]
    assert len(rows) == found


# ---- 5.39: the arm premises are written down ----


def test_every_implemented_check_name_is_documented_and_the_removed_one_is_not():
    from avocado_flash_remote import cmd_check

    missing = [n for n in cmd_check.CHECKS if f"`{n}`" not in README]
    assert not missing, missing
    assert "efibootmgr-supports-create" not in README


def test_guard_premise_and_first_boot_observation_are_documented():
    assert "L4TDefaultBootMode" in README
    assert "/proc/cmdline" in README
    assert "first boot of the eMMC entry" in README


def test_known_limits_states_the_deliberate_non_fix_for_the_record_schema():
    text = _section("Known limits")
    assert "entry_preexisting" in text
    assert "state schema is not bumped" in text
    assert "Seven debts" in text  # not a debt marker: the count stays seven


def test_boot_order_premise_is_documented():
    text = _section("The one-shot boot and its limits")
    assert "precedes `BootCurrent`" in text


def test_readme_readback_cleanup_text_names_the_mount_and_output_dirs_and_the_gates():
    text = README
    row = next(ln for ln in text.splitlines() if ln.startswith("| `readback` |"))
    assert "those paths" not in row
    assert "/run/avocado-flash/<run-id>/mnt" in row and "/run/avocado-flash/<run-id>/readback" in row
    assert "nosuid" in row and "flash lock" in row


# --- 5.41 ---


def test_exit_2_covers_a_dropped_connection_during_plan_and_connect_probes():
    text = _section("Exit codes")
    assert "`plan`" in text
    assert "cannot reach the board over ssh" in text


def test_readme_states_the_real_order_of_the_board_calls_before_stage_creates_anything():
    assert "as its first board call" not in README
    text = _section("Board prerequisites")
    assert "connect" in text and "tool probe" in text
    assert text.index("connect") < text.index("tool probe")


def test_readme_documents_the_staged_build_match_and_the_staging_directory_rules():
    assert "staged runner is from a different tool build: run stage again" in README
    assert "bundle_sha256" in README
    assert "owned by the SSH user" in README
    schema = _section("Schema version 1")
    assert "shared system director" in schema and "under `state_dir`" in schema


# --- 5.43 ---


def test_readme_documents_the_staging_containment_rules_and_the_restore_marker():
    schema = _section("Schema version 1")
    assert "pairwise" in schema and "/run/avocado-flash" in schema
    assert "temporary director" in schema and "/usr" in schema and "/var/lib/dpkg" in schema
    assert ".avocado-flash-staging" in README
    assert "only when" in README[README.index(".avocado-flash-staging") - 400 : README.index(".avocado-flash-staging") + 400]


def test_readme_readback_row_says_the_board_derives_the_directories_and_refuses_a_reused_id():
    row = next(ln for ln in README.splitlines() if ln.startswith("| `readback` |"))
    assert "derives" in row and "already exists" in row
    assert "a repeat overwrites" not in row
