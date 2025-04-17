SUMMARY = "Avocado debug tweaks extension"
DESCRIPTION = "Configuration extension with tweaks for SSH, vim, and other debug tools"

require avocado-extension.inc

# Set extension identification parameters
EXT_ID = "debug-tweaks"
EXT_VERSION = "1.0"
EXT_DESCRIPTION = "Debug tweaks for development"
EXT_TYPE = "combined"
EXT_PRIORITY = "90"

# Debug tools to include in the extension
EXT_DEPENDS = " \
    openssh-sshd \
    openssh-sftp-server \
    vim \
    strace \
    lsof \
    procps \
    tcpdump \
    pstree \
    ltrace \
    iproute2 \
    htop \
"

# Ensure the SSH server is properly configured
CONFEXTS_DIRS = "${WORKDIR}/confext-files"

do_configure() {
    # Create directory for configuration files
    mkdir -p ${WORKDIR}/confext-files/etc/ssh
    
    # Create a sshd_config file to enable root login
    cat > ${WORKDIR}/confext-files/etc/ssh/sshd_config << EOF
# Allow root login with password
PermitRootLogin yes
# Enable password authentication
PasswordAuthentication yes
EOF
}
