#!/bin/sh
# Reset a firmware TPM that comes up in dictionary-attack lockout, and give it
# a DA policy. Shared by cryptsetup-var.sh (before a TPM2 token unlock) and
# platform initrds that need a usable TPM on every boot, encrypted /var or not
# (avocado-tegra-init on Jetson).
#
# Some firmware TPMs keep no NV state across boots. Measured on Jetson Orin
# (NVIDIA OP-TEE fTPM, ms-tpm-20-ref): the seeds are stable - a credential
# sealed on one boot unseals on the next, so a TPM2 keyslot is sound - but the
# dictionary-attack state resets every boot to inLockout=1 with maxTries=0,
# and every object load then fails with TPM_RC_LOCKOUT (0x921) until a
# DictionaryAttackLockReset. lockoutAuth cannot be persisted either, so the
# reset is free; DA protection is therefore nil on such parts, which is
# acceptable here because the sealed keyslot carries a PCR policy and no auth
# value. Best-effort and silent where tpm2-tools are absent or the TPM is not
# in lockout; always exits 0.
TPM_DEV="${TPM_DEV:-/dev/tpm0}"
[ -e "$TPM_DEV" ] || exit 0
command -v tpm2_getcap >/dev/null 2>&1 || exit 0
if tpm2_getcap properties-variable 2>/dev/null | awk '/inLockout:/{f=($2==1)} END{exit !f}'; then
    echo "tpm2-lockout-reset: TPM is in dictionary-attack lockout at boot - resetting"
    tpm2_dictionarylockout --clear-lockout 2>/dev/null \
        && tpm2_dictionarylockout --setup-parameters --max-tries=32 \
               --recovery-time=600 --lockout-recovery-time=86400 2>/dev/null \
        || echo "tpm2-lockout-reset: reset failed - TPM objects will fail with TPM_RC_LOCKOUT this boot" >&2
fi
exit 0
