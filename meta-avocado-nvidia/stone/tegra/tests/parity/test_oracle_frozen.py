"""The legacy Jetson provisioning script is the parity oracle and must never change."""

import hashlib
from pathlib import Path

ORACLE = Path(__file__).parent / "legacy" / "stone-provision-tegraflash.sh"

# sha256 of meta-avocado-nvidia/stone/tegra/stone-provision-tegraflash.sh at
# commit 4afe6df92cd75d5a3bb6d41c1424a8976cdb77ba.
ORACLE_SHA256 = "20d64df68f14f185509e10f84d2934fac4c603b0423c964cc943c32f18033b4a"


def test_oracle_sha256_matches_base_blob():
    assert hashlib.sha256(ORACLE.read_bytes()).hexdigest() == ORACLE_SHA256


def test_oracle_first_line_is_bash_shebang():
    first = ORACLE.read_bytes().split(b"\n", 1)[0]
    assert first in (b"#!/bin/bash", b"#!/usr/bin/env bash")
