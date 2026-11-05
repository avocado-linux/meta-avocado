"""Host C preprocessor lookup and the wrapper that puts it first on PATH."""

import os
import shlex
import shutil
from collections.abc import Callable
from pathlib import Path

from . import EngineError

# Absolute target: a bare `exec cpp` would find this wrapper first on PATH and
# re-execute itself forever (deviation absolute-cpp-wrapper). Quoted because
# the root-run bash would otherwise expand `$`, backticks and quotes in the path.
_WRAPPER = '#!/bin/bash\nexec {target} "$@"\n'


def resolve_cpp(
    *,
    path: str,
    sdk_arch: str,
    cc: str,
    which: Callable[..., str | None] = shutil.which,
) -> str:
    """Return the absolute path of the preprocessor tegraflash should use.

    Order: the SDK-native cpp, the cross cpp named by CC, plain cpp. Target
    architecture is irrelevant for preprocessing text, so the cross cpp is fine.
    """
    names = [f"{sdk_arch}-avocadosdk-linux-cpp"]
    words = cc.split()
    if words:
        names.append(words[0].replace("gcc", "cpp", 1))
    names.append("cpp")
    for name in names:
        found = which(name, path=path)
        if not found:
            continue
        if not os.path.isabs(found):
            raise EngineError(
                f"preprocessor {name} resolved to the relative path {found}: "
                "the cpp wrapper would re-execute itself"
            )
        return found
    raise EngineError(
        "No C preprocessor (cpp) found in PATH\n"
        "Tegraflash requires cpp for DTS preprocessing.\n"
        "Ensure the SDK toolchain is properly configured."
    )


def write_wrapper(directory: str | Path, target: str) -> Path:
    """Write directory/cpp, an executable script that runs the absolute target."""
    wrapper = Path(directory) / "cpp"
    wrapper.write_text(_WRAPPER.format(target=shlex.quote(target)))
    wrapper.chmod(0o755)
    return wrapper
