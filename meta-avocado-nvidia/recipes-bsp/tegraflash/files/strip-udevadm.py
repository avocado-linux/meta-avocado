#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
Replace udevadm calls in NVIDIA's bootburn_t264_py with sysfs-only equivalents.

NVIDIA's tegraflash unified-flash python tools shell out to `udevadm info -q path`
to resolve /dev/bus/usb/<bus>/<dev> paths to canonical /sys/devices/... paths.
udevadm is unavailable in our SDK container (no nativesdk-systemd dep), so
provisioning fails at Step 5 with `udevadm info ... failed` followed by
NvError_SystemCommandFailed.

The same canonical sysfs path is reachable purely via /proc + /sys:
  - For a /dev path: stat() it, then realpath /sys/dev/char/<maj>:<min>
  - For a /sys path: realpath() it directly

Each of the three call sites here uses one of those two patterns. Comment
markers are inserted so re-runs of this script are idempotent.

Mirrors the container-aware sysfs replacements already present in
initrd-flash.sh (recipes-bsp/tegra-binaries/tegra-helper-scripts/initrd-flash.sh).
"""

import sys
import os

PATCHES = [
    # flash_utilities.py: select_socgrp's sys.path manipulation can cause
    # flash_utilities to be loaded as TWO separate module objects (one as
    # bootburn_t264_py.flash_utilities via the package import, one as a
    # top-level flash_utilities via the bootburn_t264_py dir on sys.path).
    # target_config.SetBootBurnPaths mutates one class's attrs; bootburn_lib's
    # FlashImages reads the OTHER class's attrs (still the bare class
    # defaults). Sidestep the dual-module hazard by making the class defaults
    # already-resolved absolute paths, computed from __file__ at import time.
    (
        '''import shutil
import re
import inspect
from flashtools_nverror import nverror
from flashtools_nverror import AbnormalTermination
import itertools
from multiprocessing import Pool


class flash_utilities(object):
    f_AdbTool = "adb"
    f_TegraSign = ["tegrasign_v3.py", "tegrasign_v3_internal.py" , "tegrasign_v3_util.py", \\
        "tegrasign_v3_hsm.py", "tegraopenssl", "tegrasign_v3_oemkey_t234.yaml", "xmss-sign",\\
        "tegrasign_v3_oemkey_t264.yaml"]
    f_TegraSignPriv = ["tegrasign_v3_nvkey_load.py", "tegrasign_v3_nvkey.yaml"]
    f_TegraSignDevKeyFiles = ["t234_sbk_dev.key", "t234_rsa_dev.key"]
    f_TegraBct = "tegrabct_v2"
    f_NvSkuInfo = "nvskuinfo"
    f_NvBchValidate = "nvbchvalidate"
    f_TegraRcm = "tegrarcm_v2"
    f_NvImageGen = "nvimagegen"
    f_NvImageSign = "nvimagesign"
    f_NvSimgDump = "nvsimgdump"
    f_NvDDTool = "nvdd"
    f_NvOptinFuse = "optin_fuse"
    f_CompressLz4 = "flash_lz4"
    f_Nvdtoverlay = "nvdtoverlay"
    f_Nvpt = "nvpt"
    f_TegraHost = "tegrahost_v2"
    f_TegraParser = "tegraparser_v2"
    f_NvResign = "nvresign"
    p_FlashPath = None''',
        '''import shutil
import re
import inspect
from flashtools_nverror import nverror
from flashtools_nverror import AbnormalTermination
import itertools
from multiprocessing import Pool


# Resolve flash-tool names to absolute paths at import time. Computed from
# __file__ so it works regardless of which sys.path entry loaded this module
# (select_socgrp pushes two entries that can produce two distinct module
# objects; class-attribute mutation in target_config doesn't reach the
# other copy). Falls back to PATH (shutil.which), then bare name.
_FLASH_DIR_AVOCADO = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "flash"))

def _resolve_flash_tool_avocado(name):
    p = os.path.join(_FLASH_DIR_AVOCADO, name)
    if os.path.exists(p):
        return p
    p2 = shutil.which(name)
    if p2:
        return p2
    return name


class flash_utilities(object):
    f_AdbTool = _resolve_flash_tool_avocado("adb")
    f_TegraSign = [_resolve_flash_tool_avocado(n) for n in [
        "tegrasign_v3.py", "tegrasign_v3_internal.py", "tegrasign_v3_util.py",
        "tegrasign_v3_hsm.py", "tegraopenssl", "tegrasign_v3_oemkey_t234.yaml",
        "xmss-sign", "tegrasign_v3_oemkey_t264.yaml",
    ]]
    f_TegraSignPriv = [_resolve_flash_tool_avocado(n) for n in [
        "tegrasign_v3_nvkey_load.py", "tegrasign_v3_nvkey.yaml",
    ]]
    f_TegraSignDevKeyFiles = [_resolve_flash_tool_avocado(n) for n in [
        "t234_sbk_dev.key", "t234_rsa_dev.key",
    ]]
    f_TegraBct = _resolve_flash_tool_avocado("tegrabct_v2")
    f_NvSkuInfo = _resolve_flash_tool_avocado("nvskuinfo")
    f_NvBchValidate = _resolve_flash_tool_avocado("nvbchvalidate")
    f_TegraRcm = _resolve_flash_tool_avocado("tegrarcm_v2")
    f_NvImageGen = _resolve_flash_tool_avocado("nvimagegen")
    f_NvImageSign = _resolve_flash_tool_avocado("nvimagesign")
    f_NvSimgDump = _resolve_flash_tool_avocado("nvsimgdump")
    f_NvDDTool = _resolve_flash_tool_avocado("nvdd")
    f_NvOptinFuse = _resolve_flash_tool_avocado("optin_fuse")
    f_CompressLz4 = _resolve_flash_tool_avocado("flash_lz4")
    f_Nvdtoverlay = _resolve_flash_tool_avocado("nvdtoverlay")
    f_Nvpt = _resolve_flash_tool_avocado("nvpt")
    f_TegraHost = _resolve_flash_tool_avocado("tegrahost_v2")
    f_TegraParser = _resolve_flash_tool_avocado("tegraparser_v2")
    f_NvResign = _resolve_flash_tool_avocado("nvresign")
    p_FlashPath = _FLASH_DIR_AVOCADO''',
    ),
    # bootburn_lib.py CopyTegraFlashOfflineUtilities: NVIDIA expects host
    # filesystem helpers (losetup, e2fsck, resize2fs, wr_sh.sh) to live next
    # to the flash binaries at p_fsUtils. They don't, in any sane Linux
    # distro — they're standard /usr/sbin tools. Resolve via shutil.which()
    # and skip the copy if absent (these are pushed to the target via ADB
    # for partition-resize work; the target's own initramfs already has them
    # so a missing host-side copy is non-fatal for our flow).
    (
        '''        self.shellUtils.Copy(os.path.join(p_fsUtils, "losetup"), l_p_PdkFlashPath, False, True)
        self.shellUtils.Copy(os.path.join(p_fsUtils, "e2fsck"), l_p_PdkFlashPath, False, True)
        self.shellUtils.Copy(os.path.join(p_fsUtils, "resize2fs"), l_p_PdkFlashPath, False, True)
        self.shellUtils.Copy(os.path.join(p_fsUtils, "wr_sh.sh"), l_p_PdkFlashPath, False, True)''',
        '''        # Container-aware: find host helpers via PATH instead of expecting
        # them next to NVIDIA's flash binaries (where they aren't shipped).
        # See meta-avocado-nvidia/recipes-bsp/tegraflash/files/strip-udevadm.py.
        import shutil as _shutil
        for _tool in ("losetup", "e2fsck", "resize2fs", "wr_sh.sh"):
            _src = _shutil.which(_tool) or os.path.join(p_fsUtils, _tool)
            if os.path.exists(_src):
                self.shellUtils.Copy(_src, l_p_PdkFlashPath, False, True)''',
    ),
    # bootburn_lib.py CopyTegraSign: iterates f_TegraSign which includes xmss-sign,
    # tegrasign_v3_oemkey_*.yaml, etc. Several of these aren't shipped in our
    # unified_flash/.../flash/ dir (they're keying tools for production secure
    # boot, not needed for our --no-flash dev-key flow). Make the loop tolerant
    # of missing files so the dev flow doesn't abort.
    (
        '''            self.shellUtils.Copy(tegrasignFile, l_path, False, True)''',
        '''            if os.path.exists(tegrasignFile):
                self.shellUtils.Copy(tegrasignFile, l_path, False, True)''',
    ),
    (
        '''                self.shellUtils.Copy(tegrasignNvFile, l_path, False, True)''',
        '''                if os.path.exists(tegrasignNvFile):
                    self.shellUtils.Copy(tegrasignNvFile, l_path, False, True)''',
    ),
    (
        '''            self.shellUtils.Copy(tegrasignNvKeyFile, l_path, False, True)''',
        '''            if os.path.exists(tegrasignNvKeyFile):
                self.shellUtils.Copy(tegrasignNvKeyFile, l_path, False, True)''',
    ),
    # bootburn_lib.py CopyTegraFlashUtilities: Copy(f_CompressLz4, ...).
    # flash_lz4 isn't shipped in our unified_flash/.../flash/. Make tolerant.
    (
        '''        self.shellUtils.Copy(self.flashUtils.f_CompressLz4, p_TempDumpPath, False, True)''',
        '''        if os.path.exists(self.flashUtils.f_CompressLz4):
            self.shellUtils.Copy(self.flashUtils.f_CompressLz4, p_TempDumpPath, False, True)''',
    ),
    # bootburn_adb.py resizeFilesystem: NVIDIA's flash dir ships an empty
    # placeholder for losetup (and friends); empty-file ⇒ use device's PATH,
    # nonempty ⇒ push host copy to /tmp. We don't ship the placeholder, so
    # getsize raises FileNotFoundError. Treat missing-as-empty (device PATH).
    (
        '''            if os.path.getsize(os.path.join(self.targetConfig.p_fsUtils, "losetup")) == 0:
                abs_path=""
            else:
                abs_path="/tmp/"''',
        '''            try:
                _is_empty = os.path.getsize(os.path.join(self.targetConfig.p_fsUtils, "losetup")) == 0
            except FileNotFoundError:
                _is_empty = True  # not shipped host-side; rely on device PATH
            if _is_empty:
                abs_path=""
            else:
                abs_path="/tmp/"''',
    ),
    # bootburn_adb.py resizeFilesystem: AdbPush(losetup/e2fsck/resize2fs).
    # Skip the push when the host file is missing — device already has these
    # via util-linux-losetup / e2fsprogs in the flasher initramfs.
    (
        '''            self.AdbPush(os.path.join(self.targetConfig.p_fsUtils, "losetup"))''',
        '''            _losetup_src = os.path.join(self.targetConfig.p_fsUtils, "losetup")
            if os.path.exists(_losetup_src) and os.path.getsize(_losetup_src) > 0:
                self.AdbPush(_losetup_src)''',
    ),
    (
        '''        self.AdbPush(os.path.join(self.targetConfig.p_fsUtils, "e2fsck"))''',
        '''        _e2fsck_src = os.path.join(self.targetConfig.p_fsUtils, "e2fsck")
        if os.path.exists(_e2fsck_src) and os.path.getsize(_e2fsck_src) > 0:
            self.AdbPush(_e2fsck_src)''',
    ),
    (
        '''        self.AdbPush(os.path.join(self.targetConfig.p_fsUtils, "resize2fs"))''',
        '''        _resize2fs_src = os.path.join(self.targetConfig.p_fsUtils, "resize2fs")
        if os.path.exists(_resize2fs_src) and os.path.getsize(_resize2fs_src) > 0:
            self.AdbPush(_resize2fs_src)''',
    ),
    # bootburn_lib.py FlashImages (and CopyTegraFlashUtilities, CopyTegraFlashOfflineUtilities):
    # Copy(self.flashUtils.f_NvDDTool, ...) reads the class attribute, which can
    # end up unprefixed ("nvdd" instead of "<flash_path>/nvdd") when select_socgrp
    # imports the same flash_utilities.py via two sys.path entries — modifications
    # made by target_config.SetBootBurnPaths via one module copy don't reach
    # bootburn_lib's view of the class. Sidestep the dual-module hazard by
    # resolving nvdd's actual location at the call site.
    (
        '''        self.shellUtils.Copy(self.flashUtils.f_NvDDTool, flashPath)''',
        '''        # Container-aware: f_NvDDTool may stay as the bare "nvdd" class default
        # if select_socgrp's sys.path manipulation caused flash_utilities to be
        # loaded as two separate module objects (target_config mutated one,
        # bootburn_lib reads the other). Resolve via shutil.which / explicit path.
        import shutil as _shutil
        _nvdd = self.flashUtils.f_NvDDTool
        if not os.path.isabs(_nvdd) or not os.path.exists(_nvdd):
            _resolved = _shutil.which("nvdd") or os.path.join(self.targetConfig.p_FlashPath or "", "nvdd")
            if os.path.exists(_resolved):
                _nvdd = _resolved
        self.shellUtils.Copy(_nvdd, flashPath)''',
    ),
    (
        '''        self.shellUtils.Copy(self.flashUtils.f_NvDDTool, l_p_PdkFlashPath, False, True)''',
        '''        # See note above on dual-module hazard with self.flashUtils.f_NvDDTool.
        import shutil as _shutil_nvdd
        _nvdd = self.flashUtils.f_NvDDTool
        if not os.path.isabs(_nvdd) or not os.path.exists(_nvdd):
            _resolved = _shutil_nvdd.which("nvdd") or os.path.join(self.targetConfig.p_FlashPath or "", "nvdd")
            if os.path.exists(_resolved):
                _nvdd = _resolved
        if os.path.exists(_nvdd):
            self.shellUtils.Copy(_nvdd, l_p_PdkFlashPath, False, True)''',
    ),
    (
        '''        self.shellUtils.Copy(self.flashUtils.f_NvDDTool, p_TempDumpPath)''',
        '''        # See note above on dual-module hazard with self.flashUtils.f_NvDDTool.
        import shutil as _shutil_nvdd2
        _nvdd = self.flashUtils.f_NvDDTool
        if not os.path.isabs(_nvdd) or not os.path.exists(_nvdd):
            _resolved = _shutil_nvdd2.which("nvdd") or os.path.join(self.targetConfig.p_FlashPath or "", "nvdd")
            if os.path.exists(_resolved):
                _nvdd = _resolved
        self.shellUtils.Copy(_nvdd, p_TempDumpPath)''',
    ),
    # bootburn_lib.py UpdateTargetInstance: validation loop that round-trips
    # /dev path -> udevadm -> /sys path, then checks the result is a substring
    # of the input s_PortPath. With realpath we resolve s_PortPath directly.
    (
        '''            n_TargetPath = "/dev/bus/usb/" + n_TargetBus + "/" + n_TargetDevice
            commmand = "udevadm info -q path -n " + n_TargetPath
            timeout = 0
            devread = False
            retry = True
            while (timeout <= 5) and (retry):
                time.sleep(0.05)
                timeout += 0.05
                devread = False
                l_Temp = self.shellUtils.executeShellCommand(commmand, True)
                if (isinstance(l_Temp, int) is True):
                # Command failed and returned error code
                    continue

                l_Temp = l_Temp.rstrip()
                devread = True
                if (s_PortPath.find(l_Temp) == -1):
                    continue
                retry = False''',
        '''            n_TargetPath = "/dev/bus/usb/" + n_TargetBus + "/" + n_TargetDevice
            # Container-aware: udevadm is unavailable in the SDK container.
            # s_PortPath is already a valid sysfs path (validated via os.path.exists
            # immediately above), so resolve it directly via realpath instead of
            # the udev round-trip + retry loop.
            timeout = 0
            l_Temp = os.path.realpath(s_PortPath)
            devread = True
            retry = False''',
    ),
    # bootburn_lib.py AddInstanceToFlashList: /dev path -> /sys path
    (
        '''        udevCommand = "udevadm info -q path -n " + s_TargetDevPath

        s_PortPath = self.shellUtils.executeShellCommand(udevCommand, True)

        if(isinstance(s_PortPath, int) is True):
            AbnormalTermination("Could not get port path -- " + str(s_PortPath), nverror.NvError_FileOperationFailed)

        s_PortPath = "/sys" + s_PortPath.rstrip()''',
        '''        # Container-aware: udevadm is unavailable in the SDK container.
        # Resolve /dev/bus/usb/<bus>/<dev> -> canonical /sys/devices/... path
        # via the device-major/minor symlink at /sys/dev/char/<maj>:<min>.
        try:
            _st = os.stat(s_TargetDevPath)
            s_PortPath = os.path.realpath("/sys/dev/char/{}:{}".format(os.major(_st.st_rdev), os.minor(_st.st_rdev)))
        except OSError as _e:
            AbnormalTermination("Could not get port path -- " + str(_e), nverror.NvError_FileOperationFailed)''',
    ),
    # bootburn_parser.py multi-die / -I flag: /dev path -> /sys path
    (
        '''                    path = "/dev/bus/usb/" + busNumber + "/" + deviceNumber
                    shellCommand = "udevadm info -q path -n " + path
                    portPath = self.shellUtils.executeShellCommand(shellCommand, True, True)
                    if (isinstance(portPath, int)):
                        errMsg = "failed to get the port path for " + path
                        AbnormalTermination(errMsg, nverror.NvError_SystemCommandFailed)
                    portPath = "/sys" + portPath''',
        '''                    path = "/dev/bus/usb/" + busNumber + "/" + deviceNumber
                    # Container-aware: udevadm is unavailable in the SDK container.
                    # Resolve /dev/bus/usb/<bus>/<dev> -> canonical /sys/devices/...
                    # via the device-major/minor symlink at /sys/dev/char/<maj>:<min>.
                    try:
                        _st = os.stat(path)
                        portPath = os.path.realpath("/sys/dev/char/{}:{}".format(os.major(_st.st_rdev), os.minor(_st.st_rdev)))
                    except OSError as _e:
                        AbnormalTermination("failed to get the port path for " + path + ": " + str(_e), nverror.NvError_SystemCommandFailed)''',
    ),
    # bootburn_parser.py setTargetConfigDataCmdLine: redundant /dev->/sys round-trip
    # where path is already a sysfs path
    (
        '''                    shellCommand = "udevadm info -q path -n " + devPath
                    portPathUdev = self.shellUtils.executeShellCommand(shellCommand, True, True)
                    if (isinstance(portPathUdev, int)):
                        errMsg = "failed to get the port path for " + path
                        AbnormalTermination(errMsg, nverror.NvError_SystemCommandFailed)
                    portPathUdev = "/sys" + portPathUdev''',
        '''                    # Container-aware: replaced udevadm with sysfs realpath. udevadm is
                    # unavailable in our SDK container; the canonical /sys/devices/... path
                    # it returns is the realpath of /sys/bus/usb/devices/<portPath>.
                    portPathUdev = os.path.realpath(path)''',
    ),
]


def main():
    if len(sys.argv) != 2:
        print("usage: strip-udevadm.py <tegraflash-tools-dir>", file=sys.stderr)
        return 2
    root = sys.argv[1]

    targets = [
        os.path.join(root, "unified_flash/tools/flashtools/bootburn_t264_py/bootburn_lib.py"),
        os.path.join(root, "unified_flash/tools/flashtools/bootburn_t264_py/bootburn_parser.py"),
        os.path.join(root, "unified_flash/tools/flashtools/bootburn_t264_py/flash_utilities.py"),
        os.path.join(root, "unified_flash/tools/flashtools/bootburn_t264_py/bootburn_adb.py"),
    ]

    for path in targets:
        if not os.path.isfile(path):
            print("strip-udevadm: skip (not present): " + path)
            continue
        with open(path) as f:
            src = f.read()
        new = src
        applied = 0
        for old, repl in PATCHES:
            if old in new:
                new = new.replace(old, repl)
                applied += 1
        if new != src:
            with open(path, "w") as f:
                f.write(new)
            print("strip-udevadm: patched {} ({} hunks)".format(path, applied))
        else:
            print("strip-udevadm: no matches in {} (already patched or upstream changed)".format(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
