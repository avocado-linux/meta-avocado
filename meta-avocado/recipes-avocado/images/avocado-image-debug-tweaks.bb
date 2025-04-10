DESCRIPTION = "Avocado debug tweaks extension for development"
LICENSE = "Apache-2.0"

require avocado-image-extension.bb

EXT_ID = "debug-tweaks"
EXT_VERSION = "1"

# Include debug packages and tools
EXTENSION_PACKAGES = " \
    openssh \
    strace \
    ltrace \
    lsof \
    vim \
"

# Configure SSH server for easier remote debugging
ssh_tweaks() {
    # Create sshd config directory
    install -d ${IMAGE_ROOTFS}/etc/ssh/sshd_config.d/
    
    # Configure SSH for root login
    cat > ${IMAGE_ROOTFS}/etc/ssh/sshd_config.d/10-debug-allow-root.conf << 'EOF'
# Debug configuration - allow root login
PermitRootLogin yes
EOF

    # Create the service override directory
    install -d ${IMAGE_ROOTFS}/etc/systemd/system/sshd.service.d/
    
    # Create service override to ensure it starts properly
    cat > ${IMAGE_ROOTFS}/etc/systemd/system/sshd.service.d/override.conf << 'EOF'
[Service]
# Ensure proper startup in extension environment
ExecStartPre=-/bin/mkdir -p /run/sshd
EOF

    # Create the symlink to enable the service
    install -d ${IMAGE_ROOTFS}/etc/systemd/system/multi-user.target.wants/
    ln -sf /lib/systemd/system/sshd.service ${IMAGE_ROOTFS}/etc/systemd/system/multi-user.target.wants/sshd.service
}

# Enable root login
root_tweaks() {
    # Enable root login with empty password (for development only)
    sed -i 's/root:x:/root::/' ${IMAGE_ROOTFS}/etc/passwd
    
    # Ensure the root home directory is usable
    install -d ${IMAGE_ROOTFS}/root
    install -m 0644 /dev/null ${IMAGE_ROOTFS}/root/.bash_history
    
    # Generate SSH dir structure for root
    install -d ${IMAGE_ROOTFS}/root/.ssh
    chmod 700 ${IMAGE_ROOTFS}/root/.ssh
    touch ${IMAGE_ROOTFS}/root/.ssh/authorized_keys
    chmod 600 ${IMAGE_ROOTFS}/root/.ssh/authorized_keys
}

# Create a profile.d script to set development environment
dev_env_tweaks() {
    install -d ${IMAGE_ROOTFS}/etc/profile.d
    cat > ${IMAGE_ROOTFS}/etc/profile.d/debug-env.sh << 'EOF'
# Debug environment configuration
export PS1='\[\033[1;31m\][\u@\h:\w]#\[\033[0m\] '
alias ll='ls -la'
alias rm='rm -i'
alias cp='cp -i'
alias mv='mv -i'
export PATH=$PATH:/usr/local/bin
EOF
    chmod 0755 ${IMAGE_ROOTFS}/etc/profile.d/debug-env.sh
}

# Add our customizations
ROOTFS_POSTPROCESS_COMMAND += "ssh_tweaks; root_tweaks; dev_env_tweaks;"
