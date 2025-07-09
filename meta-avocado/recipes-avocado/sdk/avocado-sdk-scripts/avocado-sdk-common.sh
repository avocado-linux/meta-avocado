#!/bin/bash

# Function to source environment setup in a subshell
run_in_sdk_env() {
    (
        if [ -f "/opt/_avocado/${AVOCADO_SDK_TARGET}/sdk/environment-setup" ]; then
            source "/opt/_avocado/${AVOCADO_SDK_TARGET}/sdk/environment-setup"
        else
            echo "Error: environment-setup not found at /opt/_avocado/${AVOCADO_SDK_TARGET}/sdk/environment-setup"
            exit 1
        fi

        # Execute the provided command
        "$@"
    )
} 
