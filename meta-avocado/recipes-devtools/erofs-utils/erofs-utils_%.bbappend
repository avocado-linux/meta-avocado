# mkfs.erofs caps the block size at the build host's page size (4 KiB on
# x86-64) unless MAX_BLOCK_SIZE is given. The SDK builds images for targets
# whose kernels use larger pages (16 KiB on the Raspberry Pi 5) and need
# page-size blocks (AVOCADO_EROFS_BLOCK_SIZE), so allow up to 64 KiB. The
# default block size is unchanged.
EXTRA_OECONF:append:class-native = " MAX_BLOCK_SIZE=65536"
EXTRA_OECONF:append:class-nativesdk = " MAX_BLOCK_SIZE=65536"
