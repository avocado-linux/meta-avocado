import stat
import subprocess

import pytest

from avocado_tegraflash import EngineError
from parity import runner
from avocado_tegraflash.cpp import resolve_cpp, write_wrapper


def fake_which(found):
    """A `which` that knows only the given name -> path mapping; records queries."""
    queries = []

    def which(name, path=None):
        queries.append((name, path))
        return found.get(name)

    which.queries = queries
    return which


def test_resolve_cpp_prefers_the_sdk_native_preprocessor():
    which = fake_which(
        {
            "x86_64-avocadosdk-linux-cpp": "/sdk/bin/x86_64-avocadosdk-linux-cpp",
            "aarch64-linux-gnu-cpp": "/usr/bin/aarch64-linux-gnu-cpp",
            "cpp": "/usr/bin/cpp",
        }
    )
    got = resolve_cpp(path="/sdk/bin:/usr/bin", sdk_arch="x86_64", cc="aarch64-linux-gnu-gcc -m64", which=which)
    assert got == "/sdk/bin/x86_64-avocadosdk-linux-cpp"


def test_resolve_cpp_searches_the_path_it_was_given():
    which = fake_which({"cpp": "/usr/bin/cpp"})
    resolve_cpp(path="/some/path", sdk_arch="x86_64", cc="", which=which)
    assert {p for _, p in which.queries} == {"/some/path"}


def test_resolve_cpp_derives_the_cross_cpp_from_the_first_word_of_cc():
    which = fake_which({"aarch64-linux-gnu-cpp": "/usr/bin/aarch64-linux-gnu-cpp", "cpp": "/usr/bin/cpp"})
    got = resolve_cpp(path="/usr/bin", sdk_arch="x86_64", cc="aarch64-linux-gnu-gcc -m64 --sysroot=/x", which=which)
    assert got == "/usr/bin/aarch64-linux-gnu-cpp"


def test_resolve_cpp_replaces_only_the_first_gcc_in_cc():
    which = fake_which({"gcc-wrap-cpp-gcc": "/usr/bin/gcc-wrap-cpp-gcc", "cpp": "/usr/bin/cpp"})
    got = resolve_cpp(path="/usr/bin", sdk_arch="x86_64", cc="gcc-wrap-gcc-gcc", which=which)
    assert got == "/usr/bin/cpp"
    assert ("cpp-wrap-gcc-gcc", "/usr/bin") in which.queries


def test_resolve_cpp_falls_back_to_plain_cpp_when_cc_is_empty():
    which = fake_which({"cpp": "/usr/bin/cpp"})
    assert resolve_cpp(path="/usr/bin", sdk_arch="x86_64", cc="", which=which) == "/usr/bin/cpp"


def test_resolve_cpp_falls_back_to_plain_cpp_when_the_cross_cpp_is_missing():
    which = fake_which({"cpp": "/usr/bin/cpp"})
    got = resolve_cpp(path="/usr/bin", sdk_arch="x86_64", cc="aarch64-linux-gnu-gcc", which=which)
    assert got == "/usr/bin/cpp"


def test_resolve_cpp_skips_cc_lookup_for_a_blank_cc():
    which = fake_which({"cpp": "/usr/bin/cpp"})
    resolve_cpp(path="/usr/bin", sdk_arch="x86_64", cc="   ", which=which)
    assert [n for n, _ in which.queries] == ["x86_64-avocadosdk-linux-cpp", "cpp"]


def test_resolve_cpp_without_any_preprocessor_names_what_is_missing():
    with pytest.raises(EngineError, match="No C preprocessor"):
        resolve_cpp(path="/usr/bin", sdk_arch="x86_64", cc="", which=fake_which({}))


@pytest.mark.deviation("absolute-cpp-wrapper")
def test_cpp_wrapper_execs_absolute_path_rejects_a_relative_result():
    which = fake_which({"cpp": "bin/cpp"})
    with pytest.raises(EngineError, match="re-execute itself"):
        resolve_cpp(path="bin", sdk_arch="x86_64", cc="", which=which)


@pytest.mark.deviation("absolute-cpp-wrapper")
def test_cpp_wrapper_execs_absolute_path_rejects_a_bare_name_result():
    which = fake_which({"x86_64-avocadosdk-linux-cpp": "x86_64-avocadosdk-linux-cpp"})
    with pytest.raises(EngineError, match="re-execute itself"):
        resolve_cpp(path="/sdk", sdk_arch="x86_64", cc="", which=which)


@pytest.mark.deviation("absolute-cpp-wrapper")
def test_cpp_wrapper_execs_absolute_path_in_the_written_text(tmp_path):
    wrapper = write_wrapper(tmp_path, "/usr/bin/cpp")
    assert wrapper.read_text() == '#!/bin/bash\nexec /usr/bin/cpp "$@"\n'


def test_write_wrapper_creates_cpp_in_the_directory_with_mode_0755(tmp_path):
    wrapper = write_wrapper(tmp_path, "/usr/bin/cpp")
    assert (wrapper, stat.S_IMODE(wrapper.stat().st_mode)) == (tmp_path / "cpp", 0o755)


def test_write_wrapper_text_matches_the_oracle_once_the_exec_target_is_masked(tmp_path):
    from parity.deviations import cpp_wrapper_equivalent

    oracle = '#!/bin/bash\nexec cpp "$@"\n'
    assert cpp_wrapper_equivalent(oracle, write_wrapper(tmp_path, "/usr/bin/cpp").read_text())


@pytest.mark.real_subprocess
def test_wrapper_runs_a_target_whose_path_has_shell_metacharacters(tmp_path):
    real_dir = tmp_path / "sdk $HOME 'q$(touch PWNED)"
    real_dir.mkdir()
    fake = real_dir / "cpp"
    record = tmp_path / "record.txt"
    fake.write_text(f'#!/bin/bash\nprintf "%s\\n" "$@" > {record}\n')
    fake.chmod(0o755)
    wrapper = write_wrapper(tmp_path, str(fake))
    out = tmp_path / "out.txt"
    try:
        with out.open("w") as sink:
            status = runner.run_in_own_session(
                ["/bin/bash", str(wrapper), "-x", "a b"], cwd=tmp_path, stdout=sink, timeout=10
            )
    except subprocess.TimeoutExpired:
        pytest.fail("wrapper overran 10 seconds")
    assert (status, record.read_text(), out.read_text()) == (0, "-x\na b\n", "")
    assert not (tmp_path / "PWNED").exists() and not (real_dir / "PWNED").exists()


@pytest.mark.real_subprocess
def test_wrapper_runs_the_stand_in_cpp_and_exits_within_the_timeout(tmp_path):
    stand_in_dir = tmp_path / "real"
    stand_in_dir.mkdir()
    stand_in = stand_in_dir / "cpp"
    stand_in.write_text('#!/bin/bash\nsed -e "s/FOO/bar/" "${@: -1}"\n')
    stand_in.chmod(0o755)
    wrapper_dir = tmp_path / "wrap"
    wrapper_dir.mkdir()
    write_wrapper(wrapper_dir, str(stand_in))
    source = tmp_path / "in.dts"
    source.write_text("FOO\n")
    out = tmp_path / "out.txt"
    env = {"PATH": f"{wrapper_dir}:{stand_in_dir}:/usr/bin:/bin"}
    try:
        with out.open("w") as sink:
            status = runner.run_in_own_session(["cpp", str(source)], env=env, stdout=sink, timeout=10)
    except subprocess.TimeoutExpired:
        pytest.fail("wrapper overran 10 seconds")
    assert (status, out.read_text()) == (0, "bar\n")


def test_mutation_bare_name_exec_is_caught_by_the_wrapper_text_test(tmp_path, mutant):
    mutated = mutant("cpp.py", "exec {target}", "exec cpp")
    wrapper = mutated.write_wrapper(tmp_path, "/usr/bin/cpp")
    assert wrapper.read_text() != '#!/bin/bash\nexec /usr/bin/cpp "$@"\n'


def test_mutation_unquoted_target_is_caught_by_the_metacharacter_test(tmp_path, mutant):
    mutated = mutant("cpp.py", "shlex.quote(target)", "target")
    wrapper = mutated.write_wrapper(tmp_path, "/opt/sdk $HOME/cpp")
    assert "/opt/sdk $HOME/cpp" in wrapper.read_text()
    assert "'/opt/sdk $HOME/cpp'" not in wrapper.read_text()


def test_mutation_accepting_relative_paths_is_caught_by_the_relative_test(mutant):
    mutated = mutant("cpp.py", "if not os.path.isabs(found):", "if False:")
    assert mutated.resolve_cpp(path="bin", sdk_arch="x", cc="", which=fake_which({"cpp": "bin/cpp"})) == "bin/cpp"
