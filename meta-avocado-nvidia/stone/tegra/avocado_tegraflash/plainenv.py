"""Read the keys the engine checks from the staged env file without running it.

initrd-flash.sh sources .env.initrd-flash with bash, so the last assignment in
any shell form wins. The engine cannot evaluate the file (that would run it as
root), so it reads only the one form it can read exactly, a plain column-0
`KEY=value`, and refuses a file that assigns a checked key any other way.
"""

import re
from pathlib import Path

from . import EngineError
from .files import read_text_preserving

CHECKED_KEYS = ("ROOTFS_IMAGE", "ROOTFS_DEVICE", "DATAFILE")

# The prefix class and the optional keyword group cover the shell forms that bind
# a variable: indentation, `export`, `declare -x`, `local`, `readonly`, `;`, `&&`,
# `||` and a subshell. `+=` and a space before `=` are matched so they refuse too.
_ASSIGNMENT = {
    key: re.compile(
        r"(^|[\s;&|(){`])(export\s+|declare\s+\S+\s+|local\s+|readonly\s+)?" + key + r"\s*\+?="
    )
    for key in CHECKED_KEYS
}


def read_plain_env(env_file: str | Path) -> dict[str, str]:
    """Map each checked key to its last plain value; a key never assigned is absent.

    Quotes are removed. Any other assignment of a checked key refuses, naming
    the file, the line and the key.
    """
    values: dict[str, str] = {}
    for number, line in enumerate(read_text_preserving(env_file).split("\n"), 1):
        if line.lstrip().startswith("#"):
            continue
        for key, pattern in _ASSIGNMENT.items():
            for match in pattern.finditer(line):
                if match.start() == 0 and match.group(0) == key + "=":
                    values[key] = line[len(key) + 1 :].strip(" \t").strip("\"'")
                    continue
                raise EngineError(
                    f"{env_file}:{number}: {key} is assigned by {line.strip()!r}, but the flash "
                    "sources this file with bash, so only a plain column 0 assignment "
                    f"({key}=...) is read"
                )
    return values
