#!/bin/bash
# KATANA-PROTOCOL — Tracks 2-5 individual production
# Each track gets a focused prompt for K3 Creative Director

# Track 2: BLOOD SHEATH
echo "=== Track 2/5: BLOOD SHEATH ==="
python3 /opt/data/skills/master-producer/master-producer/scripts/master-producer.py \
  --research --compose --director --skip-master \
  --prompt "KATANA-PROTOCOL album track 2: BLOOD SHEATH. Drift phonk / industrial trap, 140-150 BPM, F minor. Darker and more atmospheric than the opener. Cold synth pads, distorted 808 cowbells, slicing transients, mid-tempo tension builder. Slow-burning cyber-noir menace. The sound of a blood-stained scabbard in an ink-black alley. Dry recordings, natural dynamics, uncompressed. NO vocals, NO house beats, NO four-on-the-floor." \
  --quality standard --duration 260 --chat-id "${TELEGRAM_CHAT_ID}" || echo "TRACK 2 FAILED"

# Track 3: IAIDO DRIFT
echo "=== Track 3/5: IAIDO DRIFT ==="
python3 /opt/data/skills/master-producer/master-producer/scripts/master-producer.py \
  --research --compose --director --skip-master \
  --prompt "KATANA-PROTOCOL album track 3: IAIDO DRIFT. Drift phonk / industrial trap, 145-155 BPM, F minor. High-velocity. Fast hi-hat rolls, sub-bass impacts, sword draw samples as rhythmic elements. Maximum energy track. The sound of a lightning-fast iaido draw while drifting at high speed. Metallic shing samples timed to percussion. Dry recordings, natural dynamics, uncompressed. NO vocals, NO house beats, NO four-on-the-floor." \
  --quality standard --duration 260 --chat-id "${TELEGRAM_CHAT_ID}" || echo "TRACK 3 FAILED"

# Track 4: CARBON SCABBARD
echo "=== Track 4/5: CARBON SCABBARD ==="
python3 /opt/data/skills/master-producer/master-producer/scripts/master-producer.py \
  --research --compose --director --skip-master \
  --prompt "KATANA-PROTOCOL album track 4: CARBON SCABBARD. Drift phonk / industrial trap, 140-150 BPM, F minor. Industrial percussion focus. Metallic clang sounds, cyber-noir ambiance, linear groove with explosive drops. Cold, mechanical precision. The sound of a carbon fiber scabbard hitting concrete. Mechanical, relentless machine rhythm. Dry recordings, natural dynamics, uncompressed. NO vocals, NO house beats, NO four-on-the-floor." \
  --quality standard --duration 260 --chat-id "${TELEGRAM_CHAT_ID}" || echo "TRACK 4 FAILED"

# Track 5: SHADOW SEVER
echo "=== Track 5/5: SHADOW SEVER ==="
python3 /opt/data/skills/master-producer/master-producer/scripts/master-producer.py \
  --research --compose --director --skip-master \
  --prompt "KATANA-PROTOCOL album track 5: SHADOW SEVER. Drift phonk / industrial trap, 145-155 BPM, F minor. Album closer. Lethal intensity throughout, razor-sharp synth leads, cold atmospheric pads, high-speed nocturnal feel. Cinematic climax. The sound of a katana slicing through shadows at midnight. Final, devastating, no mercy. Dry recordings, natural dynamics, uncompressed. NO vocals, NO house beats, NO four-on-the-floor." \
  --quality standard --duration 260 --chat-id "${TELEGRAM_CHAT_ID}" || echo "TRACK 5 FAILED"

echo "=== ALL TRACKS COMPLETE ==="
