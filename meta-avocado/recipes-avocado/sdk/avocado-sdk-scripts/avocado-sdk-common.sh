#!/bin/bash

# Function to source environment setup in a subshell
run_in_sdk_env() {
    (
        if [ -f "/opt/_avocado/sdk/environment-setup" ]; then
            source "/opt/_avocado/sdk/environment-setup"
        else
            echo "Error: environment-setup not found at /opt/_avocado/sdk/environment-setup"
            exit 1
        fi

        # Execute the provided command
        "$@"
    )
} 
