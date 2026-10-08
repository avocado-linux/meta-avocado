# Default-multiconfig Jetson kernel. Everything is in the shared .incs so the
# PREEMPT_RT sibling (linux-yocto-rt_6.18.bbappend, built in the jetson-rt
# multiconfig) gets the identical treatment -- a `require` does not carry
# bbappends across PNs.
require recipes-kernel/linux/avocado-linux-yocto-tegra.inc
