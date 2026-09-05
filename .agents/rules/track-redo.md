# Hermes Music — Track Redo Rules

## Track Redo Behavior
When a track is redone (via 🔄 Redo button or user request):
1. **Re-produce the audio** using master-producer.py with the original brief + feedback
2. **Send the MP3** to Telegram immediately — convert FLAC or WAV to 320k MP3 if no MP3 exists
3. **Regenerate the track cover** using the varied scene system (_build_varied_scene)
4. **Apply title overlay** using overlay-title.py with Unicode styling
5. **Send the new cover** to Telegram with a regen button
6. **Update SoundCloud artwork** if the track ID is known

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
