# edk2 renamed OvmfPkgX64's TPM build knob from TPM_ENABLE to TPM2_ENABLE
# (already renamed by edk2-stable202402, scarthgap's OVMF). openembedded-core's
# PACKAGECONFIG[tpm] still passes -D TPM_ENABLE=TRUE, which the DSC no longer
# references, so it is a silent no-op: TPM2_ENABLE stays at its FALSE default and
# OvmfPkgX64 builds no hardware SecurityPkg/Tcg2Dxe - only the inert (non-TDX)
# TdTcg2 driver. The firmware never detects the qemu TPM, never installs
# Tcg2Protocol, and does no measured boot, so the kernel sees an un-started TPM
# (self-test error 256) and PCR 7 is never truly measured. systemd 258 masks
# this by sealing to an unmeasured PCR; make it real by passing the current knob.
PACKAGECONFIG[tpm] = "-D TPM2_ENABLE=TRUE,-D TPM2_ENABLE=FALSE,,"
