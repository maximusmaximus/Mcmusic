#!/bin/sh
TGPY=\ /opt/hermes/gateway/platforms/telegram.py\
VENV_PYTHON=\/opt/hermes/.venv/bin/python3\
LOG=\/opt/data/logs/startup.log\
while true; do
    if [ -f \\\ ] && ! grep -q \Album proposal callbacks\ \\\ 2>/dev/null; then
        echo \[patch-watchdog] \09/11/2026 18:17:57 re-applying...\ >> \\\
        \\\ /opt/data/scripts/patch_gateway.py >> \\\ 2>&1
        \\\ /opt/data/scripts/patch_gateway_publish.py >> \\\ 2>&1
    fi
    sleep 60
done
