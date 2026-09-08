# Shared by every recipe that compiles NVIDIA's edk2 tree: edk2-firmware-tegra,
# edk2-firmware-tegra-rcmboot and standalone-mm-optee-tegra all require the same
# edk2-firmware-tegra-<PV>.inc, so all three build the same SRCREV_edk2. Kept in
# one file because CVE_VERSION and the SRCREV it was derived from must not drift
# apart, and a per-append copy is exactly how they would.
#
# meta-tegra sets no CVE_PRODUCT, so cve-check falls back to ${BPN} and the
# firmware that owns the whole early boot scans clean on every Jetson. NVD files
# edk2 under two spellings.
CVE_PRODUCT = "tianocore:edk2 tianocore:edk_ii"

# PV is the L4T release, which shares no scheme with the YYYYMM edk2-stable
# versions NVD records, so every bounded range compares true and the recipe
# reports every edk2 CVE ever filed. edk2-stable202408 is the newest stable tag
# that is an ancestor of SRCREV_edk2 30419afc, the revision the pinned meta-tegra
# fetches from NVIDIA/edk2 branch r36.5-updates.
CVE_VERSION = "202408"

# CVE_VERSION is derived from a SRCREV these appends cannot see change: bump the
# meta-tegra pin past edk2-stable202408 and a stale 202408 silently hides every
# CVE whose range starts after it. NVD carries exact-match rows for edk2, so the
# stale direction is not the safe one.
python () {
    reviewed = "30419afc4a6ea666434f9275057f579b46a07a5f"
    if d.getVar("SRCREV_edk2") != reviewed:
        bb.warn("edk2 SRCREV moved; re-derive CVE_VERSION (now %s) from the newest "
                "edk2-stable tag that is an ancestor of it" % d.getVar("CVE_VERSION"))
}
