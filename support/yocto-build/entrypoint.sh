#!/bin/bash
set -e

# Get UID and GID from the current process
USER_ID=${USER_ID:-1000}
GROUP_ID=${GROUP_ID:-1000}

USERNAME=avocado
GROUPNAME=avocado

# If a user with USER_ID exists, find its name and delete it
if getent passwd "${USER_ID}" > /dev/null; then
    EXISTING_USERNAME=$(getent passwd "${USER_ID}" | cut -d: -f1)
    userdel -r -f "${EXISTING_USERNAME}" 2>/dev/null
fi

# If a group with GROUP_ID exists, find its name and delete it
if getent group "${GROUP_ID}" > /dev/null; then
    EXISTING_GROUPNAME=$(getent group "${GROUP_ID}" | cut -d: -f1)
    groupdel "${EXISTING_GROUPNAME}"
fi

# Create group and user
groupadd -g "${GROUP_ID}" "${GROUPNAME}"
useradd -m -u "${USER_ID}" -g "${GROUP_ID}" -s /bin/bash "${USERNAME}"

# Configure passwordless sudo for the user
echo "${USERNAME} ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/${USERNAME}
chmod 0440 /etc/sudoers.d/${USERNAME}

mkdir -p /home/avocado/.config/direnv
echo "[whitelist]" > /home/avocado/.config/direnv/config.toml
echo "prefix = [ \"/avocado-build\" ]" >> /home/avocado/.config/direnv/config.toml

chown -R "${USERNAME}:${GROUPNAME}" /home/avocado/.config

# Drop privileges and run the command
exec gosu "${USERNAME}" "$@"
