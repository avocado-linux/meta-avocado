"""Prove the autouse no-network guard in conftest.py actually fires.

The default suite must never open a network connection; real-board
operations are opt-in. These tests attempt connections and assert the
guard turns each attempt into a test failure with a clear message.
"""

import pathlib
import socket

import pytest

pytest_plugins = ["pytester"]

CONFTEST = pathlib.Path(__file__).with_name("conftest.py")
GUARD_MESSAGE = "network connection attempted"


@pytest.mark.parametrize(
    ("family", "address"),
    [
        (socket.AF_INET, ("127.0.0.1", 9)),
        (socket.AF_INET6, ("::1", 9)),
    ],
    ids=["inet", "inet6"],
)
def test_inet_connect_is_refused_with_clear_message(family, address):
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        with pytest.raises(pytest.fail.Exception, match=GUARD_MESSAGE):
            sock.connect(address)


def test_unix_connect_is_refused(tmp_path):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        with pytest.raises(pytest.fail.Exception, match=GUARD_MESSAGE):
            sock.connect(str(tmp_path / "nothing.sock"))


def test_connect_ex_is_refused():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(pytest.fail.Exception, match=GUARD_MESSAGE):
            sock.connect_ex(("127.0.0.1", 9))


def test_create_connection_is_refused():
    with pytest.raises(pytest.fail.Exception, match=GUARD_MESSAGE):
        socket.create_connection(("127.0.0.1", 9), timeout=1)


def test_guard_message_names_the_target_address():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(pytest.fail.Exception, match=r"127\.0\.0\.1"):
            sock.connect(("127.0.0.1", 9))


def test_guard_fails_a_test_even_when_code_swallows_exceptions(pytester):
    # Code under test commonly wraps connects in `except Exception` or
    # `except OSError`; the guard must still fail the test, not be eaten.
    pytester.makeconftest(CONFTEST.read_text())
    pytester.makepyfile(
        test_inner="""
        import socket

        def test_sneaky_connect():
            try:
                socket.create_connection(("192.0.2.1", 22), timeout=1)
            except Exception:
                pass
        """
    )
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(failed=1)
    result.stdout.fnmatch_lines([f"*{GUARD_MESSAGE}*192.0.2.1*"])


def test_package_is_importable_without_network():
    import avocado_flash_remote

    assert avocado_flash_remote.__doc__
