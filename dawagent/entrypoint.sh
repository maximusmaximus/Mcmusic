#!/bin/bash
# Don't use set -e — JACK may fail to start in RT mode, we handle that

echo "Starting DAWAGENT Initialization..."

# Clean stale X lock files
rm -f /tmp/.X99-lock /tmp/.X99-unix/X99 2>/dev/null || true

# Start Xvfb in the background for headless UI elements
Xvfb :99 -screen 0 1024x768x16 -nolisten tcp &
XVFB_PID=$!
sleep 1

# Start JACK with dummy backend — use --no-realtime to avoid SYS_NICE/IPC_LOCK requirements
echo "Starting JACK dummy backend (non-realtime mode)..."
jackd --no-realtime -d dummy -r 48000 -p 1024 &
JACK_PID=$!
sleep 2

# Verify JACK started
if kill -0 $JACK_PID 2>/dev/null; then
    echo "JACK started successfully (PID: $JACK_PID)"
else
    echo "WARNING: JACK failed to start, Ardour will not be available"
    echo "Falling back to headless-only mode (ffmpeg/sox processing still works)"
    JACK_PID="N/A"
fi

# Create standard directories
mkdir -p /opt/dawagent/sessions
mkdir -p /opt/dawagent/exports
mkdir -p /opt/dawagent/lua
mkdir -p /opt/dawagent/scripts
mkdir -p /opt/dawagent/watch

# Ensure scripts have execute permissions
chmod +x /opt/dawagent/scripts/*.py 2>/dev/null || true

echo "======================================"
echo "      DAWAGENT ONLINE & READY         "
echo "======================================"
echo "Xvfb PID: $XVFB_PID"
echo "JACK PID: $JACK_PID"
echo "Session Dir: /opt/dawagent/sessions"
echo "Export Dir: /opt/dawagent/exports"
echo "Watch Dir: /opt/dawagent/watch"
echo "======================================"

# Start auto-processor daemon
AUTO_PROCESSOR="/opt/dawagent/scripts/auto_processor.py"
if [ -f "$AUTO_PROCESSOR" ]; then
    python3 "$AUTO_PROCESSOR" >> /opt/dawagent/auto_processor.log 2>&1 &
    AUTO_PID=$!
    echo "Auto-processor started (PID: $AUTO_PID)"
else
    echo "WARNING: auto_processor.py not found"
    AUTO_PID=""
fi

# Keep the container alive
if [ -n "$AUTO_PID" ]; then
    wait $AUTO_PID
else
    tail -f /dev/null
fi
