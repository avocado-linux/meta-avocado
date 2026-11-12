"""Host tool setup around the flash call: adb warm-up and the flash environment."""

import os
import shutil
from collections.abc import Mapping
from pathlib import Path

from .plainenv import CHECKED_KEYS
from .runner import Runner

DEFAULT_PYTHONWARNINGS = "ignore::SyntaxWarning"
# start-server normally returns at once; the bound only stops a wedged daemon from hanging the engine.
ADB_TIMEOUT = 30.0


def _find_adb(path_env: str, data_dir: str | Path) -> str | None:
    found = shutil.which("adb", path=path_env)
    if found:
        return found
    for root, dirs, files in os.walk(data_dir):
        dirs.sort()
        if "adb" in files:
            candidate = os.path.join(root, "adb")
            if not os.path.islink(candidate):
                return candidate
    return None


def warm_adb(
    runner: Runner,
    *,
    data_dir: str | Path,
    home: str | Path,
    env: Mapping[str, str],
) -> None:
    """Start the adb daemon twice so the first-run key generation race is absorbed.

    `data_dir` is the directory searched when adb is not on PATH (the caller
    passes <data dir>/tegraflash-tools, never the whole data dir). adb is
    looked up on `env`'s PATH, the environment it then runs under.

    Best effort: any failure, including no adb at all, is swallowed. The oracle
    exports PYTHONWARNINGS before this step (line 21), so `env` carries it.
    """
    adb = _find_adb(env.get("PATH", ""), data_dir)
    if adb is None:
        return
    try:
        (Path(home) / ".android").mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    for _ in range(2):
        try:
            runner.capture([adb, "start-server"], env=env, discard_stderr=True, timeout=ADB_TIMEOUT)
        except Exception:
            pass


def flash_environment(
    base: Mapping[str, str],
    *,
    wrapper_dir: str | Path,
    work_dir: str | Path,
    pythonwarnings: str | None,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    # The flash sources the staged env files, which the engine read and checked. An exported
    # variable of the same name would stand in for a key the files leave out, unchecked.
    env = {key: value for key, value in base.items() if key not in CHECKED_KEYS}
    env["PATH"] = f"{wrapper_dir}:{work_dir}:{base.get('PATH', '')}"
    env["PYTHONWARNINGS"] = pythonwarnings or DEFAULT_PYTHONWARNINGS
    if extra:
        env.update(extra)
    return env
