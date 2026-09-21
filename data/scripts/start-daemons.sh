#!/bin/bash
# start-daemons.sh — Starts background daemons for hermes-music.
# Called by kanban dispatcher or manually after container restart.
# Idempotent: checks if processes are already running before starting.

VENV_PYTHON="/opt/hermes/.venv/bin/python3"
NOTIFY_SCRIPT="/opt/data/scripts/notify_processed.py"

# Start notify_processed.py if not already running
if ! pgrep -f "notify_processed.py" > /dev/null 2>&1; then
    echo "[daemons] Starting notify_processed.py..."
    nohup "$VENV_PYTHON" "$NOTIFY_SCRIPT" >> /opt/data/logs/notify_processed.log 2>&1 &
    echo "[daemons] notify_processed.py started (PID: $!)"
else
    echo "[daemons] notify_processed.py already running"
fi
