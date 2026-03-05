# Disable initrd support to remove the dracut dependency which is
# not available in our build environment.
PACKAGECONFIG:remove = "initrd"
