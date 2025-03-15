#!/bin/bash
# This script creates a new tmux session with two panes:
# - Left pane: Runs start-swtpm.sh to start swtpm.
# - Right pane: Waits for the TPM socket to become available and then runs run-qemu-tpm.sh.
#
# Usage: ./run-with-tpm.sh
#
# Assumes the current working directory is the build directory.
# The script's own directory contains start-swtpm.sh and run-qemu-tpm.sh.

# Derive the directory where this script resides
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The build directory is assumed to be the current working directory
BUILD_DIR="$(pwd)"
SESSION_NAME="tpm-qemu"

# Create a new detached tmux session in the build directory
tmux new-session -d -s "$SESSION_NAME" -c "$BUILD_DIR"

# In the left pane, run start-swtpm.sh
tmux send-keys -t "$SESSION_NAME:0.0" "/$SCRIPT_DIR/start-swtpm.sh" C-m

# Split the window vertically (left/right) and set the working directory
tmux split-window -h -t "$SESSION_NAME:0" -c "$BUILD_DIR"

# Build the command for the right pane that waits for the TPM socket before running run-qemu-tpm.sh
RIGHT_CMD="\
TPM_DIR=\"$BUILD_DIR/tmp/tpm-state\"; \
TPM_SOCK_FILE=\"\$TPM_DIR/socket-path\"; \
echo 'Waiting for swtpm socket to be available...'; \
TIMEOUT=30; SECONDS_ELAPSED=0; \
while [ \$SECONDS_ELAPSED -lt \$TIMEOUT ]; do \
    if [ -f \"\$TPM_SOCK_FILE\" ]; then \
        TPM_SOCK=\$(cat \"\$TPM_SOCK_FILE\"); \
        if [ -S \"\$TPM_SOCK\" ]; then \
            echo \"TPM socket is available at \$TPM_SOCK\"; \
            break; \
        fi; \
    fi; \
    sleep 1; \
    SECONDS_ELAPSED=\$((SECONDS_ELAPSED + 1)); \
done; \
if [ \$SECONDS_ELAPSED -ge \$TIMEOUT ]; then \
    echo \"Error: TPM socket did not become available within \$TIMEOUT seconds.\"; \
    exit 1; \
fi; \
echo 'Starting QEMU with TPM support...'; \
$SCRIPT_DIR/run-qemu-tpm.sh"

# Send the waiting command to the right pane
tmux send-keys -t "$SESSION_NAME:0.1" "$RIGHT_CMD" C-m

# Attach to the new tmux session
tmux attach-session -t "$SESSION_NAME"
