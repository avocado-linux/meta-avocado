import importlib
import shutil
import socket
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
PACKAGE_PARENT = TESTS_DIR.parent

for _p in (PACKAGE_PARENT, TESTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def pytest_configure(config):
    config.addinivalue_line("markers", "deviation(name): test documents a named deviation from the oracle")
    config.addinivalue_line("markers", "real_subprocess: test starts real child processes")


@pytest.fixture(autouse=True)
def _forbid_sockets(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("network access is forbidden in engine tests")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


_ENGINE = "avocado_tegraflash"


def _engine_modules() -> dict:
    return {k: v for k, v in sys.modules.items() if k == _ENGINE or k.startswith(_ENGINE + ".")}


@pytest.fixture
def mutated_root(tmp_path):
    """Factory: copy the engine package, replace one anchor in one file, return the new root.

    The anchor must occur exactly once, so a mutation can never land on the
    wrong match or silently on none.
    """
    copies = 0

    def make(source: str, old: str, new: str) -> Path:
        nonlocal copies
        copies += 1
        root = tmp_path / f"mutated-root-{copies}"
        shutil.copytree(
            PACKAGE_PARENT / _ENGINE, root / _ENGINE, ignore=shutil.ignore_patterns("__pycache__")
        )
        target = root / _ENGINE / source
        text = target.read_text()
        assert text.count(old) == 1, f"anchor matches {text.count(old)} places, expected one: {old!r}"
        target.write_text(text.replace(old, new))
        return root

    return make


@pytest.fixture
def mutant(mutated_root):
    """Factory: import a module (default: `source`'s own) from a mutated copy of the engine.

    sys.modules and sys.path are put back before the module is returned; the
    mutant keeps its own package objects (its own EngineError class, so match
    on messages), and the real engine is untouched for the rest of the test.
    """

    def load(source: str, old: str, new: str, module: str | None = None):
        root = mutated_root(source, old, new)
        saved = _engine_modules()
        for key in saved:
            del sys.modules[key]
        sys.path.insert(0, str(root))
        try:
            return importlib.import_module(f"{_ENGINE}.{module or Path(source).stem}")
        finally:
            sys.path.remove(str(root))
            for key in _engine_modules():
                del sys.modules[key]
            sys.modules.update(saved)

    return load
