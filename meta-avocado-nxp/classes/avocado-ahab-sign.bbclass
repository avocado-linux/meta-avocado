# Shared AHAB signing for i.MX9 containers.
#
# Two things get signed on this platform - the imx-boot container carrying
# SPL/ATF/U-Boot, and the OS container carrying the kernel and its device tree.
# They are signed the same way with the same keys, so the key handling and the
# fail-closed check live here rather than in each consumer. A divergence
# between two copies of this would be a security bug, not a style problem.
#
# Signing is one SPSDK call: `nxpimage ahab sign` takes a finished container,
# locates its header and signature block itself, and emits a signed copy. NXP's
# cst_signer wrapper only shells the same command on the AHAB path.

# Directory holding the AHAB PKI tree, laid out as `nxpcrypto pki-tree ahab`
# emits it: crts/ for the SRK certificates, keys/ for the private keys. There
# is deliberately no default that works - see the check below.
AVOCADO_AHAB_KEYS_DIR ?= ""

# Which of the four SRKs signs. The fused hash covers the whole table, so
# rotating to another index does not need a re-fuse.
AVOCADO_AHAB_SRK_ID ?= "0"

# SPSDK is a host tool rather than a recipe: it is a large Python application,
# and the private keys it needs are out-of-band anyway, so a hermetic build is
# not reachable for this step. Point this at the directory holding `nxpimage`.
AVOCADO_AHAB_SPSDK_BINDIR ?= ""

AVOCADO_AHAB_KEY_TYPE ?= "secp384r1"
AVOCADO_AHAB_FAMILY ?= "mimx9352"

python () {
    if not bb.utils.contains('DISTRO_FEATURES', 'ahab', True, False, d):
        return
    if not d.getVar('AVOCADO_AHAB_KEYS_DIR'):
        bb.fatal("DISTRO_FEATURES contains 'ahab' but AVOCADO_AHAB_KEYS_DIR is "
                 "unset. Set it to an AHAB PKI tree (see "
                 "meta-avocado-nxp/docs/imx93-srk-pki.md) or drop the feature. "
                 "Refusing to produce an unsigned artifact for a target that "
                 "asked for secure boot.")
    if not d.getVar('AVOCADO_AHAB_SPSDK_BINDIR'):
        bb.fatal("DISTRO_FEATURES contains 'ahab' but AVOCADO_AHAB_SPSDK_BINDIR "
                 "is unset. SPSDK provides `nxpimage`, which does the signing; "
                 "install it (`uv tool install spsdk`) and point this at its bin "
                 "directory.")
}

# avocado_ahab_sign <unsigned-container> <signed-output>
#
# Writes its own SPSDK config next to the output. Absolute key paths are used
# rather than SIG_DATA_PATH-relative ones so a missing file names itself.
avocado_ahab_sign() {
    _in="$1"
    _out="$2"
    _keys="${AVOCADO_AHAB_KEYS_DIR}"
    _nxpimage="${AVOCADO_AHAB_SPSDK_BINDIR}/nxpimage"
    _srk="${AVOCADO_AHAB_SRK_ID}"
    _kt="${AVOCADO_AHAB_KEY_TYPE}"
    _yaml="$_out.spsdk.yaml"

    if [ ! -x "$_nxpimage" ]; then
        bbfatal "nxpimage not executable at $_nxpimage"
    fi
    if [ ! -f "$_in" ]; then
        bbfatal "no container to sign at $_in"
    fi

    _signer="$_keys/keys/SRK${_srk}_${_kt}_key.pem"
    if [ ! -f "$_signer" ]; then
        bbfatal "signing key $_signer not found; AVOCADO_AHAB_KEYS_DIR must hold a tree as produced by 'nxpcrypto pki-tree ahab'"
    fi

    cat > "$_yaml" <<EOF
family: ${AVOCADO_AHAB_FAMILY}
revision: latest
srk_set: oem
used_srk_id: $_srk
signer: $_signer
srk_table:
  flag_ca: false
  hash_algorithm: sha384
  srk_array:
    - $_keys/crts/SRK0_${_kt}_cert.pem
    - $_keys/crts/SRK1_${_kt}_cert.pem
    - $_keys/crts/SRK2_${_kt}_cert.pem
    - $_keys/crts/SRK3_${_kt}_cert.pem
EOF

    "$_nxpimage" ahab sign --force -c "$_yaml" -b "$_in" -o "$_out"

    if [ ! -f "$_out" ]; then
        bbfatal "signing reported success but produced no $_out"
    fi

    # Read the result back rather than trusting the exit status: a container
    # that merely round-tripped through the tool would deploy happily and fail
    # only on a part whose fuses cannot be unburned.
    if ! "$_nxpimage" ahab info -f ${AVOCADO_AHAB_FAMILY} -b "$_out" \
            | grep -q 'Signed by OEM keys'; then
        bbfatal "$_out carries no OEM signature"
    fi
}
