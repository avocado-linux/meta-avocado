"""Read the keys the engine checks from the staged env files without running them.

initrd-flash.sh sources `.env.initrd-flash` and then, when present,
`.presigning-vars` with bash, so the last assignment in any shell form wins.
Both files come from the BSP and carrier, which are as trusted as the flash
tools that source them as root: this reader guards against mistakes and drift
in generated files, not against a hostile overlay. It never executes a file. It
reads one form it can read exactly (a plain column-0 `KEY=value`) and refuses a
line that uses a checked key in any other way.
"""

import re
from pathlib import Path

from . import EngineError
from .files import read_text_preserving

PRESIGNING_FILE = ".presigning-vars"

_NAME = re.compile(r"[A-Za-z0-9._+-]+")
_DEVICE = re.compile(r"[A-Za-z0-9._-]+")
_FLAG = re.compile(r"[01]")
# key -> (allowed value shape, what it is)
_SHAPES = {
    "ROOTFS_IMAGE": (_NAME, "a bare file name"),
    "DATAFILE": (_NAME, "a bare file name"),
    "TOSIMGFILENAME": (_NAME, "a bare file name"),
    "ROOTFS_DEVICE": (_DEVICE, "a device name"),
    "EXTERNAL_ROOTFS_DRIVE": (_FLAG, "0 or 1"),
    "NO_INTERNAL_STORAGE": (_FLAG, "0 or 1"),
}
CHECKED_KEYS = tuple(_SHAPES)
_BARE_WORD = {key: re.compile(rf"(?<![A-Za-z0-9_]){key}(?![A-Za-z0-9_])") for key in CHECKED_KEYS}
_FOLLOW = frozenset({"eval", "source", "."})
# Reserved words that may precede a command in bash without being the command.
_KEYWORDS = frozenset({"then", "do", "else", "elif", "if", "while", "until", "!", "time"})
# Commands that run the next command word; `-` options between them are skipped.
_WRAPPERS = frozenset({"builtin", "command", "exec", "env"})
_SEPARATORS = re.compile(r"&&|\|\||[;&|(){}`\n]")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")
_REDIRECTION = re.compile(r"[0-9]*(?:<<?<?|>>?)")
# The lookbehind keeps a long digit run from being rescanned from every digit in it.
_DUP_REDIRECTION = re.compile(r"(?<![0-9])[0-9]*[<>]&[0-9-]*")


class EnvValue(str):
    """A checked key's value, with the file and line it was assigned on."""

    path: Path
    line: int

    def __new__(cls, value: str, path: Path, line: int) -> "EnvValue":
        self = super().__new__(cls, value)
        self.path = path
        self.line = line
        return self

    def __getnewargs__(self) -> tuple[str, Path, int]:
        # copy, deepcopy and pickle call __new__ with these, so they must be supplied; the instance
        # dict (path, line) is restored afterwards, so the values passed here are not observable.
        return (str(self), self.path, self.line)

    @property
    def where(self) -> str:
        return f"{self.path}:{self.line}"


def _refuse(path: Path, number: int, why: str) -> EngineError:
    return EngineError(
        f"{path}:{number}: {why}, but the flash sources this file with bash, "
        "so only plain column-0 assignments (KEY=value) are read"
    )


def _is_read(line: str, match: re.Match) -> bool:
    """True for `$KEY` and `${KEY}`, the only spellings of a read."""
    start, end = match.span()
    if line[start - 1 : start] == "$":
        return True
    return line[start - 2 : start] == "${" and line[end : end + 1] == "}"


def _unquoted(word: str) -> str:
    """The word as bash sees it after quote removal: `'source'`, `"."` and `\\source` name the same command."""
    return word.replace("'", "").replace('"', "").replace("\\", "")


def _command_word(words: list[str]) -> str:
    """The first word that is the command, after keywords, assignments, redirections and wrappers; '' if none.

    One forward pass over an index: a line of millions of prefix words must not cost more than its length.
    """
    i, n = 0, len(words)
    while i < n:
        word = words[i]
        if word in _KEYWORDS or _ASSIGNMENT.match(word):
            i += 1
            if word == "time":
                # `time -p cmd`: the options belong to time, not to the command.
                while i < n and words[i].startswith("-"):
                    i += 1
        elif (redirect := _REDIRECTION.match(word)) is not None:
            # `> file` carries its target in the next word; `>file` carries it itself.
            i += 1 if redirect.end() < len(word) else 2
        elif _unquoted(word) in _WRAPPERS:
            i += 1
            while i < n and words[i].startswith("-"):
                i += 1
        else:
            return _unquoted(word)
    return ""


def _follows_code(line: str) -> bool:
    """True when any command word of the line is `.`, `source` or `eval`."""
    for segment in _SEPARATORS.split(_DUP_REDIRECTION.sub(" ", line)):
        if _command_word(segment.split()) in _FOLLOW:
            return True
    return False


def _value(path: Path, number: int, key: str, raw: str) -> str:
    raw = raw.rstrip(" \t")
    if "\r" in raw:
        raise _refuse(path, number, f"{key} has a carriage return in {raw!r} (a CRLF line ending), which bash keeps in the value")
    if re.search(r"[ \t]#", raw):
        raise _refuse(path, number, f"{key} has a trailing comment in {raw!r}, which bash drops and the engine does not read")
    if raw[:1] in ("'", '"') and raw:
        if len(raw) < 2 or raw[-1] != raw[0]:
            raise _refuse(path, number, f"{key} has an unmatched quote in {raw!r}")
        raw = raw[1:-1]
    shape, what = _SHAPES[key]
    if not shape.fullmatch(raw) or set(raw) == {"."}:
        raise _refuse(path, number, f"{key} is {raw!r}, not {what}")
    return raw


def _read_file(path: Path, values: dict[str, EnvValue]) -> None:
    text = read_text_preserving(path)
    if "\0" in text:
        raise EngineError(f"{path}: contains a NUL byte, which bash drops when it sources the file")
    for number, line in enumerate(text.split("\n"), 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if _follows_code(stripped):
            raise _refuse(path, number, f"{line.strip()!r} runs code the engine cannot follow")
        if line.endswith("\\"):
            raise _refuse(path, number, "a trailing backslash joins this line to the next")
        for key, pattern in _BARE_WORD.items():
            for match in pattern.finditer(line):
                if _is_read(line, match):
                    continue
                if match.start() == 0 and line[match.end() : match.end() + 1] == "=":
                    values[key] = EnvValue(_value(path, number, key, line[match.end() + 1 :]), path, number)
                    continue
                raise _refuse(path, number, f"{key} is used by {line.strip()!r}")


def read_plain_env(env_file: str | Path) -> dict[str, EnvValue]:
    """Map each checked key to the value the flash ends up with; a key never assigned is absent.

    Each value is a str that also carries the `path` and `line` of the
    assignment that won, so a refusal can cite the file the value came from.

    Reads `env_file`, then `.presigning-vars` beside it when present, in the
    order the flash sources them, so the later file wins. Quotes are removed.
    Any other use of a checked key refuses, naming the file, the line and the key.
    """
    env_file = Path(env_file)
    values: dict[str, EnvValue] = {}
    _read_file(env_file, values)
    presigning = env_file.parent / PRESIGNING_FILE
    if presigning.is_file():
        _read_file(presigning, values)
    return values
