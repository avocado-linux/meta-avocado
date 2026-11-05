import os
import stat

from avocado_tegraflash.toolchain import ADB_TIMEOUT, flash_environment, warm_adb


class Recorder:
    def __init__(self, status=0, raises=None):
        self.calls = []
        self.envs = []
        self.status = status
        self.raises = raises

    def run(self, argv, *, cwd=None, env=None):
        self.calls.append(list(argv))
        if self.raises:
            raise self.raises
        return self.status

    def capture(self, argv, *, cwd=None, env=None, discard_stderr=False, timeout=None):
        self.calls.append(list(argv))
        self.envs.append(env)
        if self.raises:
            raise self.raises
        return self.status, ""


def make_exe(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_warm_adb_runs_start_server_exactly_twice_for_adb_on_path(tmp_path):
    adb = make_exe(tmp_path / "bin" / "adb")
    rec = Recorder()
    warm_adb(rec, env={"PATH": str(adb.parent)}, data_dir=tmp_path / "none", home=tmp_path / "h")
    assert rec.calls == [[str(adb), "start-server"]] * 2


def test_warm_adb_falls_back_to_adb_under_data_dir(tmp_path):
    tools = tmp_path / "tools"
    adb = tools / "sub" / "platform-tools" / "adb"
    adb.parent.mkdir(parents=True)
    adb.write_text("x")
    rec = Recorder()
    warm_adb(rec, env={"PATH": str(tmp_path / "empty")}, data_dir=tools, home=tmp_path / "h")
    assert rec.calls == [[str(adb), "start-server"]] * 2


def test_warm_adb_ignores_adb_outside_the_directory_it_is_given(tmp_path):
    tools = tmp_path / "data" / "tegraflash-tools"
    (tools / "platform-tools").mkdir(parents=True)
    wanted = tools / "platform-tools" / "adb"
    wanted.write_text("x")
    (tmp_path / "data" / "adb").write_text("decoy")
    rec = Recorder()
    warm_adb(rec, env={"PATH": ""}, data_dir=tools, home=tmp_path / "h")
    assert rec.calls == [[str(wanted), "start-server"]] * 2


def test_warm_adb_prefers_path_over_data_dir(tmp_path):
    on_path = make_exe(tmp_path / "bin" / "adb")
    tools = tmp_path / "tools"
    (tools).mkdir()
    (tools / "adb").write_text("x")
    rec = Recorder()
    warm_adb(rec, env={"PATH": str(on_path.parent)}, data_dir=tools, home=tmp_path / "h")
    assert rec.calls[0][0] == str(on_path)


def test_warm_adb_without_any_adb_runs_nothing_and_raises_nothing(tmp_path):
    rec = Recorder()
    warm_adb(rec, env={"PATH": str(tmp_path / "empty")}, data_dir=tmp_path / "missing", home=tmp_path / "h")
    assert rec.calls == []


def test_warm_adb_with_empty_data_dir_runs_nothing(tmp_path):
    (tmp_path / "tools").mkdir()
    rec = Recorder()
    warm_adb(rec, env={"PATH": ""}, data_dir=tmp_path / "tools", home=tmp_path / "h")
    assert rec.calls == []


def test_warm_adb_ignores_a_directory_named_adb(tmp_path):
    tools = tmp_path / "tools"
    (tools / "adb").mkdir(parents=True)
    rec = Recorder()
    warm_adb(rec, env={"PATH": ""}, data_dir=tools, home=tmp_path / "h")
    assert rec.calls == []


def test_warm_adb_creates_dot_android_under_home(tmp_path):
    adb = make_exe(tmp_path / "bin" / "adb")
    home = tmp_path / "h" / "deep"
    warm_adb(Recorder(), env={"PATH": str(adb.parent)}, data_dir=tmp_path, home=home)
    assert (home / ".android").is_dir()


def test_warm_adb_accepts_existing_dot_android(tmp_path):
    adb = make_exe(tmp_path / "bin" / "adb")
    (tmp_path / "h" / ".android").mkdir(parents=True)
    rec = Recorder()
    warm_adb(rec, env={"PATH": str(adb.parent)}, data_dir=tmp_path, home=tmp_path / "h")
    assert len(rec.calls) == 2


def test_warm_adb_runs_both_calls_when_the_first_fails(tmp_path):
    adb = make_exe(tmp_path / "bin" / "adb")
    rec = Recorder(status=1)
    warm_adb(rec, env={"PATH": str(adb.parent)}, data_dir=tmp_path, home=tmp_path / "h")
    assert len(rec.calls) == 2


def test_warm_adb_swallows_a_runner_exception_and_still_tries_the_second(tmp_path):
    adb = make_exe(tmp_path / "bin" / "adb")
    rec = Recorder(raises=OSError("boom"))
    warm_adb(rec, env={"PATH": str(adb.parent)}, data_dir=tmp_path, home=tmp_path / "h")
    assert len(rec.calls) == 2


def test_warm_adb_swallows_an_unusable_home(tmp_path):
    adb = make_exe(tmp_path / "bin" / "adb")
    blocker = tmp_path / "file"
    blocker.write_text("x")
    rec = Recorder()
    warm_adb(rec, env={"PATH": str(adb.parent)}, data_dir=tmp_path, home=blocker)
    assert len(rec.calls) == 2


def test_warm_adb_runs_with_the_given_environment_so_pythonwarnings_is_set(tmp_path):
    # Oracle 21 exports PYTHONWARNINGS before the warm-up at 41-42.
    adb = make_exe(tmp_path / "bin" / "adb")
    rec = Recorder()
    env = {"PATH": str(adb.parent), "PYTHONWARNINGS": "ignore::SyntaxWarning"}
    warm_adb(rec, data_dir=tmp_path / "none", home=tmp_path / "h", env=env)
    assert rec.envs == [env, env]


def test_flash_environment_orders_path_wrapper_work_caller():
    env = flash_environment(
        {"PATH": "/usr/bin:/bin"}, wrapper_dir="/w", work_dir="/b", pythonwarnings=None
    )
    assert env["PATH"] == "/w:/b:/usr/bin:/bin"


def test_flash_environment_defaults_pythonwarnings():
    env = flash_environment({}, wrapper_dir="/w", work_dir="/b", pythonwarnings=None)
    assert env["PYTHONWARNINGS"] == "ignore::SyntaxWarning"


def test_flash_environment_keeps_callers_pythonwarnings():
    env = flash_environment({}, wrapper_dir="/w", work_dir="/b", pythonwarnings="error")
    assert env["PYTHONWARNINGS"] == "error"


def test_flash_environment_empty_pythonwarnings_gets_default():
    env = flash_environment({}, wrapper_dir="/w", work_dir="/b", pythonwarnings="")
    assert env["PYTHONWARNINGS"] == "ignore::SyntaxWarning"


def test_flash_environment_without_caller_path_has_no_trailing_separator():
    env = flash_environment({}, wrapper_dir="/w", work_dir="/b", pythonwarnings=None)
    assert env["PATH"] == "/w:/b:"


def test_flash_environment_copies_extra():
    env = flash_environment(
        {}, wrapper_dir="/w", work_dir="/b", pythonwarnings=None, extra={"AVOCADO_KERNEL_CMDLINE_EXTRA": "a=b"}
    )
    assert env["AVOCADO_KERNEL_CMDLINE_EXTRA"] == "a=b"


def test_flash_environment_keeps_other_base_variables_and_does_not_mutate_base():
    base = {"PATH": "/p", "HOME": "/h"}
    env = flash_environment(base, wrapper_dir="/w", work_dir="/b", pythonwarnings=None)
    assert env["HOME"] == "/h" and base == {"PATH": "/p", "HOME": "/h"} and env is not base


def test_flash_environment_extra_wins_over_base():
    env = flash_environment(
        {"X": "1"}, wrapper_dir="/w", work_dir="/b", pythonwarnings=None, extra={"X": "2"}
    )
    assert env["X"] == "2"


def test_flash_environment_works_with_os_environ_type_mapping():
    env = flash_environment(os.environ, wrapper_dir="/w", work_dir="/b", pythonwarnings=None)
    assert isinstance(env, dict)


def test_warm_adb_discards_stderr_and_bounds_each_call(tmp_path):
    # Oracle 41-42: `start-server >/dev/null 2>&1`, so nothing may reach a provision log.
    adb = make_exe(tmp_path / "bin" / "adb")
    seen = []

    class Spy(Recorder):
        def capture(self, argv, *, cwd=None, env=None, discard_stderr=False, timeout=None):
            seen.append((discard_stderr, timeout))
            return super().capture(argv, cwd=cwd, env=env)

    warm_adb(Spy(), env={"PATH": str(adb.parent)}, data_dir=tmp_path, home=tmp_path / "h")
    assert seen == [(True, ADB_TIMEOUT)] * 2
