#!/bin/bash
set -e

VENV_PYTHON="/opt/hermes/.venv/bin/python3"
LOG_DIR="/opt/data/logs"
mkdir -p "$LOG_DIR"

# ── Patch: Add album proposal button handler to gateway ──
PATCH_SCRIPT="/opt/data/scripts/patch_gateway.py"
if [ -f "$PATCH_SCRIPT" ]; then
    "$VENV_PYTHON" "$PATCH_SCRIPT" 2>&1 | tee -a "$LOG_DIR/startup.log"
fi

# ── Patch: Add publish button handler to gateway ──
PATCH_PUB="/opt/data/scripts/patch_gateway_publish.py"
if [ -f "$PATCH_PUB" ]; then
    "$VENV_PYTHON" "$PATCH_PUB" 2>&1 | tee -a "$LOG_DIR/startup.log"
fi

# ── Restore SoundCloud credential symlink ──
SC_TOKENS="/opt/data/home/.hermes/credentials/soundcloud_tokens.json"
SC_LINK="/root/.hermes/credentials/soundcloud_tokens.json"
if [ -f "$SC_TOKENS" ] && [ ! -f "$SC_LINK" ]; then
    mkdir -p "$(dirname "$SC_LINK")"
    ln -sf "$SC_TOKENS" "$SC_LINK"
    echo "[wrapper] Restored SoundCloud credential symlink"
fi

# ── Daemon: notify_processed.py ──
NOTIFY_SCRIPT="/opt/data/scripts/notify_processed.py"
if [ -f "$NOTIFY_SCRIPT" ]; then
    "$VENV_PYTHON" "$NOTIFY_SCRIPT" >> "$LOG_DIR/notify_processed.log" 2>&1 &
    echo "[wrapper] notify_processed.py started (PID: $!)"
fi

# ── Cron: propose_albums.py every other day ──
PROPOSE_SCRIPT="/opt/data/scripts/propose_albums.py"
if [ -f "$PROPOSE_SCRIPT" ]; then
    (
        while true; do
            day=$((10#$(date +%d)))
            if [ $((day % 2)) -eq 1 ]; then
                marker="/tmp/.propose_ran_$(date +%Y%m%d)"
                if [ ! -f "$marker" ]; then
                    echo "[cron] Running propose_albums.py (day $day)" >> "$LOG_DIR/propose_albums.log"
                    "$VENV_PYTHON" "$PROPOSE_SCRIPT" >> "$LOG_DIR/propose_albums.log" 2>&1
                    touch "$marker"
                fi
            fi
            sleep 3600
        done
    ) &
    echo "[wrapper] Album proposal cron started"
fi

# ── Patch SOUL.md after gateway writes it ──
# Gateway entrypoint regenerates SOUL.md on every start — our patch adds rules 7-11
PATCH_SOUL="/opt/data/scripts/patch_soul.py"
if [ -f "$PATCH_SOUL" ]; then
    (sleep 3 && "$VENV_PYTHON" "$PATCH_SOUL" >> "$LOG_DIR/startup.log" 2>&1) &
    echo "[wrapper] SOUL.md patcher scheduled"
fi

# ── Watchdog: health check every 10 minutes ──
WATCHDOG="/opt/data/scripts/watchdog.py"
if [ -f "$WATCHDOG" ]; then
    (
        sleep 60  # Let gateway fully initialize first
        while true; do
            "$VENV_PYTHON" "$WATCHDOG" >> "$LOG_DIR/watchdog.log" 2>&1
            sleep 600  # Every 10 minutes
        done
    ) &
    echo "[wrapper] Watchdog cron started (10 min interval)"
fi

# ── Hand off to gateway ──
exec /opt/hermes/entrypoint.sh "$@"
