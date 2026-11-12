"""The legacy Jetson provisioning script is the parity oracle and must never change."""

import hashlib
from pathlib import Path

ORACLE = Path(__file__).parent / "legacy" / "stone-provision-tegraflash.sh"

# sha256 of meta-avocado-nvidia/stone/tegra/stone-provision-tegraflash.sh at
# commit 53ea1993d15ce42b9e648086ea36dc95da0f3511 (the NVMe PCIe pin; its parent
# 4afe6df92cd75d5a3bb6d41c1424a8976cdb77ba hashed to
# 20d64df68f14f185509e10f84d2934fac4c603b0423c964cc943c32f18033b4a).
ORACLE_SHA256 = "d5e735b432d4f158f30c0c76db91f184eeafcb1e05c1b72a21664a1e4d2c69a9"


def test_oracle_sha256_matches_base_blob():
    assert hashlib.sha256(ORACLE.read_bytes()).hexdigest() == ORACLE_SHA256


def test_oracle_first_line_is_bash_shebang():
    first = ORACLE.read_bytes().split(b"\n", 1)[0]
    assert first in (b"#!/bin/bash", b"#!/usr/bin/env bash")
