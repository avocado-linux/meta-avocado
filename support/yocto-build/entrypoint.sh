#!/bin/bash
set -e

# Get UID and GID from the current process
USER_ID=${USER_ID:-1000}
GROUP_ID=${GROUP_ID:-1000}

USERNAME=avocado
GROUPNAME=avocado

# Check if group exists, create if not
if ! getent group "${GROUP_ID}" > /dev/null; then
    groupadd -g "${GROUP_ID}" "${GROUPNAME}"
else
    GROUPNAME=$(getent group "${GROUP_ID}" | cut -d: -f1)
fi

# Check if user exists, create if not
if ! getent passwd "${USER_ID}" > /dev/null; then
    useradd -m -u "${USER_ID}" -g "${GROUP_ID}" -s /bin/bash "${USERNAME}"
else
    USERNAME=$(getent passwd "${USER_ID}" | cut -d: -f1)
fi

# Configure passwordless sudo for the user
echo "${USERNAME} ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/${USERNAME}
chmod 0440 /etc/sudoers.d/${USERNAME}

mkdir -p /home/avocado/.config/direnv
echo "[whitelist]" > /home/avocado/.config/direnv/config.toml
echo "prefix = [ \"/avocado-build\" ]" >> /home/avocado/.config/direnv/config.toml

chown -R "${USERNAME}:${GROUPNAME}" /home/avocado/.config

# Drop privileges and run the command
exec gosu "${USERNAME}" "$@"
