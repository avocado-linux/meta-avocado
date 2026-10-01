"""Shared fixtures for the remote-medium tests.

Every test here runs behind an autouse guard that refuses any socket
connection. Real-board operations are opt-in; the default suite uses
stubs only, so a connect attempt is a bug in the test or the code under
test and must fail loudly.
"""

import pathlib
import socket
import sys

import pytest

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parents[2]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _refuse(method):
    def guarded(self, address, *args, **kwargs):
        # pytest.fail raises a BaseException subclass, so code wrapping the
        # connect in `except Exception` / `except OSError` cannot swallow it.
        pytest.fail(
            f"network connection attempted: socket.{method}({address!r}) "
            f"on family {socket.AddressFamily(self.family).name}; the default "
            "suite must use stubs, real-board access is opt-in",
            pytrace=False,
        )

    return guarded


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _refuse("connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse("connect_ex"))
