#!/bin/sh
# Host test: the udev matches base-files writes into 61-avocado-var.rules, and
# the device avocado-var-device.bbclass hands avocado-var-grow and
# cryptsetup-var, for each AVOCADO_VAR_PART_DEV form. Runs the layers' own
# functions. Run: sh meta-avocado-distro/recipes-core/base-files/tests/test-var-udev-match.sh
set -eu
here=$(cd "$(dirname "$0")" && pwd)
exec python3 - "$here/../base-files_%.bbappend" "$here/../../../../meta-avocado/classes/avocado-var-device.bbclass" <<'PY'
import re, sys

class Fatal(Exception):
    pass

class bb:
    @staticmethod
    def fatal(msg):
        raise Fatal(msg)

class D:
    def __init__(self, v):
        self.v = v
    def getVar(self, _):
        return self.v

ns = {"bb": bb}
for path in sys.argv[1:]:
    for fn in re.finditer(r"^def \w+\(d\):\n(?:(?:    .*|)\n)+", open(path).read(), re.M):
        exec(fn.group(0), ns)
call = lambda name, v: ns[name](D(v))

ROOT = ', PROGRAM=="avocado-on-root-disk %k"'
LINK = "/dev/disk/by-avocado/var-partition"
cases = [
    # value, udev match, root-disk condition, device for var-grow/cryptsetup-var
    ("/dev/disk/by-partlabel/var", 'ENV{ID_PART_ENTRY_NAME}=="var"', ROOT, LINK),
    ("PARTUUID=4d21b016-b534-45c2-a9fb-5c16e091fd2d",
     'ENV{ID_PART_ENTRY_UUID}=="4d21b016-b534-45c2-a9fb-5c16e091fd2d"', ROOT, LINK),
    ("/dev/mmcblk0p3", 'KERNEL=="mmcblk0p3"', "", "/dev/mmcblk0p3"),
    ("none", "", "", "/dev/disk/by-partlabel/var"),
]
fail = 0
for value, match, root, device in cases:
    got = (call("avocado_var_udev_match", value), call("avocado_var_root_disk_match", value),
           call("avocado_var_device", value))
    good = got == (match, root, device)
    print(("ok" if good else "FAIL") + f" - {value} -> {got}")
    fail |= not good
try:
    call("avocado_var_udev_match", "/dev/disk/by-uuid/abc")
    print("FAIL - an unsupported /dev/disk form was accepted"); fail = 1
except Fatal:
    print("ok - an unsupported /dev/disk form fails the build")
sys.exit(fail)
PY
