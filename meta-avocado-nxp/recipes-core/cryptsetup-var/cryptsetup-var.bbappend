# The i.MX var-key backend (SoC-UID-derived Argon2id key) for every i.MX
# machine: the OCOTP UID it reads is published by soc-imx8m and soc-imx9 alike.
FILESEXTRAPATHS:prepend:avocado-imx := "${THISDIR}/files:"

# i.MX 8M hardware key backend: a CAAM black key supplies the passphrase of a
# second keyslot (files/var-hwkey.sh; contract in cryptsetup-var.sh). Only the
# 8M family has CAAM - i.MX 9 has ELE, which gets its own backend - so this is
# scoped to mx8m rather than to every i.MX. NXP's caam-keygen (keyctl-caam)
# creates and imports black blobs; caam-crypt runs the tagged-key AES transform
# through AF_ALG (kernel: caam.cfg turns on CAAM_TK_API and USER_API_SKCIPHER).
SRC_URI:append:mx8m-nxp-bsp = " file://var-hwkey.sh"
RDEPENDS:${PN}:append:mx8m-nxp-bsp = " keyctl-caam crypto-af-alg"
