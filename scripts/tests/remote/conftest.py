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


_GOOD_ARG = b"console=ttyS0 module_blacklist=nvme,nvme_core,pcie_tegra194 quiet"


def _good_boot_header() -> bytes:
    hdr = bytearray(2048)
    hdr[0:8] = b"ANDROID!"
    hdr[64 : 64 + len(_GOOD_ARG)] = _GOOD_ARG
    return bytes(hdr)


@pytest.fixture(autouse=True, scope="session")
def _staged_header_fallback():
    """Tests stage fake file names that do not exist on disk.

    The staged boot-image check reads a real file by default; where the file is
    absent, stand in a valid header carrying the shipped profile's argument so
    unrelated tests are not refused. Tests of the check itself inject a
    ``file_reader`` and never reach this.
    """
    from avocado_flash_remote import arm

    real = arm.read_staged_header

    def fallback(path):
        try:
            return real(path)
        except FileNotFoundError:
            return _good_boot_header()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(arm, "read_staged_header", fallback)
        yield
