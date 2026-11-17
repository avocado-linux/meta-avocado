"""Case matrix for the legacy-vs-engine parity run.

Profile cases are derived from the stone manifests that name the legacy
provision script, so a new manifest or profile adds cases without an edit here.

`Case` is a frozen dataclass. `env` is a tuple of (name, value) pairs, which
keeps the case hashable; read it with `dict(case.env)` or `case.env_dict`.
`scenario` (stubs.py schema) and `tree` (keyword arguments of
fixtures.build_tree) are plain dicts and are excluded from the hash.

The `tree["drop"]` names are the contract with fixtures.build_tree:
`tegraflash_bsp` (the manifest image key of the BSP directory),
`internal-flash-emmc.xml` (the eMMC layout file inside the BSP) and
`appuuid` (the APPUUID placeholder in the external layout). `tree["carrier"]`
is a mapping of carrier.env entries. `tree["shadow_link"]`,
`tree["absolute_images"]` and `tree["tos_name"]` are described at
fixtures.build_tree.

A case with a `deviation` is expected to differ from the oracle, and only in
what that listed deviation (deviations.py) explains; test_parity checks both.

No case uses two boards or an unknown profile: the engine refuses both on
purpose (deviations one-board-only, unknown-profile-refused) and engine unit
tests cover them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPT = "stone-provision-tegraflash.sh"
STONE_DIR = Path(__file__).resolve().parents[3]

APX = "Bus 001 Device 005: ID 0955:7523 NVIDIA Corp. APX"
EMMC_PROFILES = ("tegraflash-mmc", "tegraflash-emmc")
NVME_PROFILES = ("tegraflash", "tegraflash-nvme")
PIN = "0005:01:00.0"
CARRIER = {"CARRIER_LABEL": "Parity Carrier", "CARRIER_FV_BOARDID": "9999", "CARRIER_ENV_EXTRA": "carrier-value"}


@dataclass(frozen=True)
class Case:
    id: str
    manifest: Path
    profile: str
    env: tuple[tuple[str, str], ...] = ()
    scenario: dict[str, Any] = field(default_factory=dict, hash=False)
    tree: dict[str, Any] = field(default_factory=dict, hash=False)
    deviation: str = ""

    @property
    def env_dict(self) -> dict[str, str]:
        return dict(self.env)


def _script_profiles(manifest: Path) -> list[str]:
    try:
        data = json.loads(manifest.read_text())
    except (OSError, ValueError):
        return []
    profiles = (data.get("provision") or {}).get("profiles") or {}
    return [n for n, p in profiles.items() if isinstance(p, dict) and p.get("script") == SCRIPT]


def _declares_sd_device(manifest: Path) -> bool:
    data = json.loads(manifest.read_text())
    return "sd_device" in (data.get("storage_devices", {}).get("rootdisk", {}).get("tegraflash") or {})


def _has_carrier_image(manifest: Path) -> bool:
    data = json.loads(manifest.read_text())
    return "tegraflash_carrier_bsp" in data["storage_devices"]["rootdisk"]["images"]


def _case(manifest: Path, profile: str, variant: str, env=None, scenario=None, tree=None, deviation="") -> Case:
    full_env = {"AVOCADO_PROVISION_PROFILE": profile, **(env or {})}
    return Case(
        id=f"{manifest.stem}/{profile}/{variant}",
        manifest=manifest,
        profile=profile,
        env=tuple(sorted(full_env.items())),
        scenario={"lsusb": [[APX]], **(scenario or {})},
        tree={"carrier": None, "kernel": True, "drop": (), **(tree or {})},
        deviation=deviation,
    )


def all_cases(stone_dir: Path | None = None) -> list[Case]:
    root = Path(stone_dir) if stone_dir is not None else STONE_DIR
    out: list[Case] = []
    no_board_done = False
    for manifest in sorted(root.glob("*.json")):
        profiles = _script_profiles(manifest)
        if not profiles:
            continue
        for profile in profiles:
            out.append(_case(manifest, profile, "base"))
            if profile in EMMC_PROFILES:
                out.append(_case(manifest, profile, "missing-emmc-layout", tree={"drop": ("internal-flash-emmc.xml",)}))
            if profile == "tegraflash-sd":
                out.append(_case(manifest, profile, "sd-env", env={"AVOCADO_PROVISION_SD_DEVICE": "mmcblk1"}))
                out.append(
                    _case(manifest, profile, "sd-malformed", env={"AVOCADO_PROVISION_SD_DEVICE": "/dev/mmcblk1"})
                )
                if not _declares_sd_device(manifest):
                    out.append(_case(manifest, profile, "sd-undeclared"))
        first = profiles[0]
        # The wait for a board runs before any manifest-specific stage and the
        # oracle polls 60 times with about a dozen stub calls each, so this case
        # runs for the first manifest only.
        no_board = [] if no_board_done else [_case(manifest, first, "no-board", scenario={"lsusb": [[]]})]
        no_board_done = True
        out += [
            _case(manifest, first, "no-kernel", tree={"kernel": False}),
            _case(manifest, first, "carrier", tree={"carrier": dict(CARRIER)}),
            _case(manifest, first, "erase-emmc", env={"ERASE_EMMC": "1"}),
            _case(manifest, first, "erase-only", env={"ERASE_ONLY": "1"}),
            _case(manifest, first, "boardctl-ok", env={"BOARDCTL_TARGET": "topo"}, scenario={"boardctl_rc": 0, "lsusb": [[], [APX]]}),
            _case(manifest, first, "boardctl-fail", env={"BOARDCTL_TARGET": "topo"}, scenario={"boardctl_rc": 1, "lsusb": [[], [APX]]}),
            _case(manifest, first, "third-poll", scenario={"lsusb": [[], [], [APX]]}),
            _case(manifest, first, "missing-bsp", tree={"drop": ("tegraflash_bsp",)}),
            _case(manifest, first, "missing-appuuid", tree={"drop": ("appuuid",)}),
            _case(manifest, first, "flash-exit-7", scenario={"flash_rc": 7}),
            *no_board,
            _case(manifest, first, "absolute-image-name", tree={"absolute_images": ("rootfs", "tegraflash_tos")}),
            _case(
                manifest,
                first,
                "absolute-tos-name",
                tree={"tos_name": "/abs-tos.img"},
                deviation="tos-name-bare-filename",
            ),
            _case(
                manifest,
                first,
                "priority-trailing-comma",
                scenario={"dtbo_priority": "usb,nvme,emmc,sd,ufs,"},
            ),
            _case(
                manifest,
                first,
                "no-env-file",
                tree={"drop": (".env.initrd-flash",)},
                deviation="env-file-missing-status",
            ),
        ]
        nvme = next((p for p in profiles if p in NVME_PROFILES), None)
        if nvme:
            out += [
                _case(manifest, nvme, "nvme-pin-env", env={"AVOCADO_PROVISION_NVME_PCI": PIN}),
                _case(manifest, nvme, "nvme-pin-malformed", env={"AVOCADO_PROVISION_NVME_PCI": "nvme1n1"}),
            ]
            if _has_carrier_image(manifest):
                out += [
                    _case(manifest, nvme, "nvme-pin-carrier", tree={"carrier": {**CARRIER, "CARRIER_NVME_PCI": f'"{PIN}"'}}),
                    _case(
                        manifest,
                        nvme,
                        "nvme-pin-override",
                        env={"AVOCADO_PROVISION_NVME_PCI": PIN},
                        tree={"carrier": {**CARRIER, "CARRIER_NVME_PCI": "'0003:01:00.0'"}},
                    ),
                ]
        emmc = next((p for p in profiles if p in EMMC_PROFILES), None)
        if emmc:
            # Only the nvme branch reads the knob, so a malformed value must change nothing here.
            out.append(_case(manifest, emmc, "nvme-pin-ignored", env={"AVOCADO_PROVISION_NVME_PCI": "nvme1n1"}))
        if _has_carrier_image(manifest):
            out += [
                _case(
                    manifest,
                    first,
                    "shadow-link",
                    tree={"carrier": dict(CARRIER), "shadow_link": True},
                    deviation="symlink-destination-replaced",
                ),
                _case(
                    manifest,
                    first,
                    "carrier-no-label",
                    tree={"carrier": {"CARRIER_FV_BOARDID": "9999"}},
                    deviation="carrier-label-optional",
                ),
            ]
    return out


def report(ran: int, planned: int) -> str:
    return f"cases: {ran}/{planned} run"


def shortfall(ran: int, planned: int) -> bool:
    return ran < planned
