#!/bin/bash

# Run the repository setup script if a directory is mounted
if [ -d "/repo" ]; then
    echo "Setting up repositories from /repo..."
    /usr/local/bin/setup-repo.sh /repo
else
    echo "Warning: No RPM directory mounted at /repo"
fi

# Start nginx
exec nginx -g "daemon off;" 
