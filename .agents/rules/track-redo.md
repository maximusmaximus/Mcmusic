# Hermes Music — Track Redo Rules

## Track Redo Behavior
When a track is redone (via 🔄 Redo button or user request):
1. **Re-produce the audio** using master-producer.py with the original brief + feedback
2. **Wait for DAWAGENT mastering** — check /opt/data/dawagent/exports/{slug}/ for mastered files. Wait up to 90 seconds if a session exists but master isn't ready yet
3. **Send the mastered MP3** to Telegram immediately — prefer DAWAGENT master over raw production. Label it accordingly (DAWAGENT Mastered / Pre-Master / Raw Mix)
4. **Regenerate the track cover** using the varied scene system (_build_varied_scene)
5. **Apply title overlay** using overlay-title.py with Unicode styling
6. **Upscale the cover to 3000×3000** via Venice API /image/upscale (scale=4, creativity=0.01, center-crop to 3000×3000)
7. **Send the new cover** to Telegram with a regen button
8. **Update SoundCloud artwork** with the 3000×3000 version if track ID is known

## Audio Priority Order
1. DAWAGENT mastered MP3 (/opt/data/dawagent/exports/{slug}/{slug}_MASTER.mp3)
2. DAWAGENT mastered FLAC → convert to MP3
3. Production master MP3
4. Production master FLAC → convert to MP3
5. Mix WAV → convert to MP3

## Cover Art Pipeline
All covers follow this pipeline:
1. Venice generate at 1024×1024 (grok-imagine-image-quality)
2. overlay-title.py applies styled Unicode text
3. User reviews at 1024×1024 (Telegram compresses anyway)
4. On approval → Venice upscale to 4096×4096 → center-crop to 3000×3000
5. 3000×3000 version used for SoundCloud upload
6. Original 1024×1024 backed up as _1k.png

## Cover Art Variation
Track covers must be a cohesive series with variation:
- Each track gets a unique environment, weather, camera angle, lighting, and color accent
- Use _build_varied_scene() in album_pipeline.py for all cover generation
- Covers should tell a visual story across the album
- Variation should be interesting and relevant to theme, not repetitive

## Never Do
- Never redo ALL tracks when user asks to redo a single track
- Never skip sending the MP3 audio file after a redo
- Never skip regenerating the cover after a redo
- Never send a raw mix when a DAWAGENT mastered version exists
- Never upload 1024×1024 covers to SoundCloud — always upscale to 3000×3000 first
