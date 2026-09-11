#!/bin/bash
# replay-album.sh — Extend all previews in a folder to full-length tracks
# Usage: replay-album.sh <preview_folder> [duration=180] [quality=standard] [target=streaming]
set -euo pipefail

PREVIEW_DIR="${1:?Usage: replay-album.sh <preview_folder> [duration] [quality] [target]}"
DURATION="${2:-180}"
QUALITY="${3:-standard}"
TARGET="${4:-streaming}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PRODUCER="$SCRIPT_DIR/master-producer.py"

if [ ! -f "$PRODUCER" ]; then
    echo "❌ master-producer.py not found at $PRODUCER"
    exit 1
fi

# Find all production_plan.json files
PLANS=()
while IFS= read -r plan; do
    PLANS+=("$plan")
done < <(find "$PREVIEW_DIR" -name "production_plan.json" -type f | sort)

if [ ${#PLANS[@]} -eq 0 ]; then
    echo "❌ No production_plan.json files found in $PREVIEW_DIR"
    echo "   Make sure previews were generated with --director flag"
    exit 1
fi

echo "╔══════════════════════════════════════════════════════════╗"
echo "║          🔒 REPLAY ALBUM — Preview Lock Mode            ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Preview folder: $PREVIEW_DIR"
echo "  Plans found:    ${#PLANS[@]}"
echo "  Duration:       ${DURATION}s"
echo "  Quality:        $QUALITY"
echo "  Target:         $TARGET"
echo ""

TRACK_NUM=0
FAILED=0

for plan in "${PLANS[@]}"; do
    TRACK_NUM=$((TRACK_NUM + 1))
    
    # Extract title from plan
    TITLE=$(python3 -c "
import json
with open('$plan') as f:
    p = json.load(f)
print(p.get('title', 'Track $TRACK_NUM'))
" 2>/dev/null || echo "Track $TRACK_NUM")
    
    # Extract original prompt (use title as fallback prompt)
    PROMPT=$(python3 -c "
import json
with open('$plan') as f:
    p = json.load(f)
main = p.get('stems', {}).get('main', {})
print(main.get('prompt', p.get('title', 'instrumental track'))[:200])
" 2>/dev/null || echo "$TITLE")
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Track $TRACK_NUM/${#PLANS[@]}: $TITLE"
    echo "  Plan:  $plan"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    if python3 "$PRODUCER" \
        --plan "$plan" \
        --prompt "$PROMPT" \
        --duration "$DURATION" \
        --quality "$QUALITY" \
        --target "$TARGET"; then
        echo "  ✅ $TITLE complete"
    else
        echo "  ❌ $TITLE failed"
        FAILED=$((FAILED + 1))
    fi
    echo ""
done

echo "╔══════════════════════════════════════════════════════════╗"
echo "║                   📀 ALBUM COMPLETE                     ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo "  Tracks: $TRACK_NUM total, $((TRACK_NUM - FAILED)) succeeded, $FAILED failed"
echo "  Duration: ${DURATION}s per track"
echo "  Quality: $QUALITY"
