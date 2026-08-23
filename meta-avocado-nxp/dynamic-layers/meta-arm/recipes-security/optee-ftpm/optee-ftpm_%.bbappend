# meta-arm ships optee-ftpm with COMPATIBLE_MACHINE ?= "invalid" and opts each
# board in by name (genericarm64, qemuarm64, qemuarm-secureboot, sbsa-ref).
# i.MX93 is not on that list, so with meta-arm present the recipe still refuses
# to build and the TA never reaches BL32.
#
# The machine name rather than an imx93-frdm override: only the Avocado machine
# has the initramfs, tee-supplicant and PCR-7 enroll wiring that makes the TA
# useful, so opting in the whole NXP family would advertise a TPM on boards that
# cannot bring one up.
COMPATIBLE_MACHINE:avocado-imx93-frdm = "avocado-imx93-frdm"
