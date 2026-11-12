"""Recording stubs for the external programs the legacy provision script starts.

The legacy script and the new engine both run against these stubs. Each stub
appends one JSON line per call to a shared log and answers from a scenario
file, so the two runs can be compared decision for decision.

Scenario keys (all optional):
  lsusb          list of outputs, each a list of lsusb lines. A bare
                 `lsusb -d 0955:` call prints the next output (the last one
                 repeats). `lsusb -d 0955:<pid>` filters the output most
                 recently printed, exits 1 when nothing matches, and never
                 advances.
  boardctl_rc    exit status of boardctl (default 0)
  adb_rc         exit status of adb (default 0)
  dtbo_priority  value fdtget returns before any fdtput; null makes fdtget
                 fail (default "usb,nvme,emmc,sd,ufs")
  fdtput_takes   false makes fdtput exit 0 without storing (default true)
  flash_rc       exit status of initrd-flash (default 0)
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

STUB_TOOLS = (
    "lsusb",
    "boardctl",
    "adb",
    "fdtget",
    "fdtput",
    "cpp",
    "x86_64-avocadosdk-linux-cpp",
    "mkbootimg",
    "avocado-tegra-bootimg",
    "initrd-flash",
)

_PRELUDE = '''\
import json
import os
import sys

LOG = __LOG__
SCENARIO = __SCENARIO__
TOOL = __TOOL__


def scenario():
    try:
        with open(SCENARIO) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def record():
    rec = {
        "tool": TOOL,
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "PATH": os.environ.get("PATH"),
        "PYTHONWARNINGS": os.environ.get("PYTHONWARNINGS"),
        "AVOCADO_KERNEL_CMDLINE_EXTRA": os.environ.get("AVOCADO_KERNEL_CMDLINE_EXTRA"),
    }
    data = (json.dumps(rec) + "\\n").encode()
    fd = os.open(LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


record()
'''

_BODY_RC = '''
sys.exit(int(scenario().get(__KEY__, 0)))
'''

_BODY_LSUSB = '''
STATE = LOG + ".lsusb"


def read_index():
    try:
        with open(STATE) as fh:
            return int(fh.read() or "0")
    except FileNotFoundError:
        return 0


outputs = scenario().get("lsusb") or [[]]
args = sys.argv[1:]
needle = ""
if "-d" in args and args.index("-d") + 1 < len(args):
    needle = args[args.index("-d") + 1].lower()
bare = needle in ("", "0955:")
printed = read_index()  # bare calls so far
if bare:
    cur = min(printed, len(outputs) - 1)
    with open(STATE, "w") as fh:
        fh.write(str(printed + 1))
else:
    cur = min(max(printed - 1, 0), len(outputs) - 1)
hits = [ln for ln in outputs[cur] if ("id " + needle) in ln.lower()] if needle else list(outputs[cur])
for ln in hits:
    print(ln)
sys.exit(0 if hits else 1)
'''

_BODY_FDT = '''
# fdtget/fdtput share a property store beside the dtbo: <dtbo>.props.json
def split(argv):
    pos = [a for a in argv if not a.startswith("-")]
    # `-t s` consumes a value; drop it
    if "-t" in argv:
        i = argv.index("-t")
        pos = [a for j, a in enumerate(argv) if j != i and j != i + 1 and not a.startswith("-")]
    return pos


def load(store):
    try:
        with open(store) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


pos = split(sys.argv[1:])
if len(pos) < 3:
    print("%s: missing arguments" % TOOL, file=sys.stderr)
    sys.exit(1)
dtbo, node, prop = pos[0], pos[1], pos[2]
store = dtbo + ".props.json"
key = node + " " + prop
sc = scenario()
if TOOL == "fdtget":
    props = load(store)
    if key in props:
        print(props[key])
        sys.exit(0)
    default = sc.get("dtbo_priority", "usb,nvme,emmc,sd,ufs")
    if default is None:
        print("Error: couldn't read %s" % dtbo, file=sys.stderr)
        sys.exit(1)
    print(default)
    sys.exit(0)
if sc.get("fdtput_takes", True):
    props = load(store)
    props[key] = " ".join(pos[3:])
    with open(store, "w") as fh:
        json.dump(props, fh)
sys.exit(0)
'''

_BODY_NOOP = '''
sys.exit(0)
'''


def _body(tool: str) -> str:
    if tool == "lsusb":
        return _BODY_LSUSB
    if tool in ("fdtget", "fdtput"):
        return _BODY_FDT
    keyed = {"boardctl": "boardctl_rc", "adb": "adb_rc", "initrd-flash": "flash_rc"}
    if tool in keyed:
        return _BODY_RC.replace("__KEY__", repr(keyed[tool]))
    return _BODY_NOOP


def write_stubs(stub_dir: Path, log_path: Path, scenario_path: Path) -> None:
    """Write one executable stub per tool into stub_dir.

    The log and scenario paths are baked into each stub, so a stub works from
    any cwd and any environment. initrd-flash is a template: the harness copies
    it into the staged BSP directory, where the script runs ./initrd-flash.
    """
    stub_dir = Path(stub_dir)
    stub_dir.mkdir(parents=True, exist_ok=True)
    log_abs = str(Path(log_path).resolve())
    scenario_abs = str(Path(scenario_path).resolve())
    for tool in STUB_TOOLS:
        prelude = (
            _PRELUDE.replace("__LOG__", repr(log_abs))
            .replace("__SCENARIO__", repr(scenario_abs))
            .replace("__TOOL__", repr(tool))
        )
        path = stub_dir / tool
        path.write_text("#!/usr/bin/env python3\n" + prelude + _body(tool))
        os.chmod(
            path,
            stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH,
        )
