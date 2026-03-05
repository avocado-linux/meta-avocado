# Enable nativesdk build for runc in the SDK
BBCLASSEXTEND = "nativesdk"

# Disable seccomp and selinux for nativesdk
PACKAGECONFIG:remove:class-nativesdk = "seccomp selinux"
