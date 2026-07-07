# edk2-stable202511 renamed the OVMF TPM build knob from TPM_ENABLE to TPM2_ENABLE
# (openembedded-core's PACKAGECONFIG[tpm] still passes -D TPM_ENABLE=TRUE, which is
# now a no-op). Without TPM2_ENABLE=TRUE, OvmfPkgX64 builds no hardware Tcg2Dxe -
# only the inert TDX TdTcg2 driver - so the firmware never detects the qemu TPM,
# never installs Tcg2Protocol, and does no measured boot. The guest kernel then
# sees an un-started TPM (error 256) and systemd-cryptenroll's PCR-7 seal fails.
# Override the flag to the current knob. See docs/migrations/scarthgap-to-wrynose.md.
PACKAGECONFIG[tpm] = "-D TPM2_ENABLE=TRUE,-D TPM2_ENABLE=FALSE,,"
