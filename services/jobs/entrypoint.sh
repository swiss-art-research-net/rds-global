#!/bin/sh
set -e

# Run startup task if it exists
if task --list | grep -q '^[*[:space:]]*startup:'; then
    echo "Running startup task..."
    task startup
fi

exec tail -f /dev/null