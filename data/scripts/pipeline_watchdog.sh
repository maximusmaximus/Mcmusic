#!/bin/bash
# pipeline_watchdog.sh — Monitors album_pipeline.py and resumes unfinished, in-flight pipelines.
# Automatically detects and discards published releases or stale states to prevent rogue message loops.

VENV_PYTHON="/opt/hermes/.venv/bin/python3"
PIPELINE_STATE="/opt/data/music/pipeline_state.json"
PIPELINE_SCRIPT="/opt/data/scripts/album_pipeline.py"
LOG_DIR="/opt/data/logs"
CRASH_FILE="/tmp/.pipeline_crashes"

mkdir -p "$LOG_DIR"
sleep 30  # Let gateway initialize first

while true; do
    if [ -f "$PIPELINE_STATE" ] && ! pgrep -f "album_pipeline.py" > /dev/null 2>&1; then
        STATE_STATUS=$("$VENV_PYTHON" -c "
def check():
    import json, os
    try:
        if not os.path.exists('$PIPELINE_STATE'):
            return 'stale'
        with open('$PIPELINE_STATE', 'r', encoding='utf-8') as f:
            state = json.load(f)
        album = state.get('proposal', {}).get('album', '').lower().replace(' ', '-').replace('_', '-')
        if not album:
            return 'stale'
        # Check if a different album was selected in current_proposals.json
        try:
            with open('/opt/data/music/proposals/current_proposals.json', 'r', encoding='utf-8') as pf:
                props = json.load(pf)
            sel = props.get('selected_slug') or props.get('selected', '').lower().replace(' ', '-').replace('_', '-')
            if sel and sel != album:
                return 'stale'
        except Exception:
            pass
        # Check if already published
        for rpath in [f'/opt/data/music/releases/{album}/release.json', f'/opt/data/music/albums/{album}/release.json']:
            if os.path.exists(rpath):
                try:
                    with open(rpath, 'r', encoding='utf-8') as rf:
                        rj = json.load(rf)
                    if rj.get('status') == 'published' or rj.get('soundcloud', {}).get('track_ids'):
                        return 'published'
                except Exception:
                    pass
        return 'valid'
    except Exception:
        return 'stale'
print(check())
" 2>/dev/null)

        if [ "$STATE_STATUS" = "published" ] || [ "$STATE_STATUS" = "stale" ]; then
            echo "[pipeline-watchdog] $(date) Album published or replaced by new selection ($STATE_STATUS), removing state" >> "$LOG_DIR/pipeline.log"
            rm -f "$PIPELINE_STATE"
        elif [ "$STATE_STATUS" = "valid" ]; then
            NOW=$(date +%s)
            touch "$CRASH_FILE"
            COUNT=$(awk -v now="$NOW" '$1 > now - 600' "$CRASH_FILE" 2>/dev/null | wc -l)
            if [ "$COUNT" -ge 3 ]; then
                echo "[pipeline-watchdog] $(date) 🚨 Crash loop detected ($COUNT restarts in 10m). Pausing auto-resume." >> "$LOG_DIR/pipeline.log"
            else
                echo "$NOW" >> "$CRASH_FILE"
                echo "[pipeline-watchdog] $(date) Incomplete pipeline state exists but no pipeline running — resuming..." >> "$LOG_DIR/pipeline.log"
                "$VENV_PYTHON" -B "$PIPELINE_SCRIPT" --resume >> "$LOG_DIR/pipeline.log" 2>&1 &
                sleep 300
            fi
        else
            echo "[pipeline-watchdog] $(date) Unknown state status: $STATE_STATUS, ignoring." >> "$LOG_DIR/pipeline.log"
        fi
    fi
    sleep 60
done
