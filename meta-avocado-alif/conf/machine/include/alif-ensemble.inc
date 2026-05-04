# Shared bring-up settings for the Alif Ensemble SoC family.
#
# Pulled into every avocado-<ensemble-board>.conf so kernel/TF-A/imaging
# defaults stay consistent across boards in the family. Per-board overrides
# (DTBs, MACHINE_FEATURES, OSPI layout) stay in the machine .conf.

# Vendor BSP providers from meta-alif-ensemble.
PREFERRED_PROVIDER_virtual/kernel ?= "linux-alif"

# linux-alif emits xipImage for execute-in-place from OSPI.
KERNEL_IMAGETYPE ?= "xipImage"

# Suppress the upstream WIC pipeline. Avocado provisions via stone profiles
# (img / sd / serial); the stone manifest carries the OSPI + SD layouts.
WKS_FILE = ""
WKS_IMAGE_FSTYPES = ""
