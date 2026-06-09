#!/bin/ash
set -e

# Get UID and GID from environment variables
USER_ID=${USER_ID:-1000}
GROUP_ID=${GROUP_ID:-1000}

echo "DEBUG: USER_ID=${USER_ID}, GROUP_ID=${GROUP_ID}"

USERNAME=nginx-user
GROUPNAME=nginx-group

# If a user with USER_ID exists, find its name and delete it
if getent passwd "${USER_ID}" > /dev/null 2>&1; then
    EXISTING_USERNAME=$(getent passwd "${USER_ID}" | cut -d: -f1)
    deluser "${EXISTING_USERNAME}" 2>/dev/null || true
fi

# If a group with GROUP_ID exists, find its name and delete it
if getent group "${GROUP_ID}" > /dev/null 2>&1; then
    EXISTING_GROUPNAME=$(getent group "${GROUP_ID}" | cut -d: -f1)
    delgroup "${EXISTING_GROUPNAME}" 2>/dev/null || true
fi

# Create group and user
addgroup -g "${GROUP_ID}" "${GROUPNAME}"
adduser -D -u "${USER_ID}" -G "${GROUPNAME}" -s /bin/sh "${USERNAME}"

# Create and set permissions for nginx directories
mkdir -p /var/cache/nginx \
         /var/run \
         /var/log/nginx

# Create log files (they're symlinks to stdout/stderr in nginx:alpine)
touch /var/log/nginx/access.log /var/log/nginx/error.log

# Add user directive to main nginx.conf (after the comment line)
sed -i "1a user ${USERNAME} ${GROUPNAME};" /etc/nginx/nginx.conf

chown -R "${USERNAME}:${GROUPNAME}" \
    /var/cache/nginx \
    /var/run \
    /var/log/nginx \
    /usr/share/nginx/html \
    /etc/nginx

# Run the command (nginx will drop privileges based on user directive)
exec "$@"
