#!/bin/bash

# Function to check if the package-repo service is up
check_repo() {
    wget -q --spider http://package-repo:80/
    return $?
}

# Poll until the package-repo service is up
echo "Waiting for package-repo service to be ready..."
while ! check_repo; do
    echo "Package repo not ready yet, waiting..."
    sleep 5
done

echo "Package repo is ready!"
entrypoint "$@"
