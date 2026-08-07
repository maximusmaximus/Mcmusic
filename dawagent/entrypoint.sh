#!/bin/bash
set -e

echo "Starting DAWAGENT Initialization..."

# Start Xvfb in the background for headless UI elements
Xvfb :99 -screen 0 1024x768x16 -nolisten tcp &
XVFB_PID=$!

# Wait for Xvfb to be ready
sleep 1

# Start JACK with dummy backend
echo "Starting JACK dummy backend..."
jackd -m -d dummy -r 48000 -p 1024 &
JACK_PID=$!

# Wait for JACK to be ready
sleep 2

# Create standard directories
mkdir -p /opt/dawagent/sessions
mkdir -p /opt/dawagent/exports
mkdir -p /opt/dawagent/lua
mkdir -p /opt/dawagent/scripts

# Ensure scripts have execute permissions
chmod +x /opt/dawagent/scripts/*.py 2>/dev/null || true

echo "======================================"
echo "      DAWAGENT ONLINE & READY         "
echo "======================================"
echo "Xvfb PID: $XVFB_PID"
echo "JACK PID: $JACK_PID"
echo "Session Dir: /opt/dawagent/sessions"
echo "Export Dir: /opt/dawagent/exports"
echo "======================================"

# Keep the container alive
tail -f /dev/null
