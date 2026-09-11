# Cover Redo Workflow — Presenting Multiple Options

When a user asks to redo a playlist or album cover, the workflow established
in this session uses **two distinct concepts** generated and presented side by
side for the user to choose from.

## Workflow

1. **Research the playlist** — Load the SoundCloud page to see track titles,
   play counts, description. Understand the vibe before generating.

2. **Generate Option 1 (first concept)** — Run gen_artwork.py with --notes
   describing the first scene concept. The background is generated and upscaled.
   Then manually overlay the title using the venv Python.

3. **Generate Option 2 (second concept)** — Delete the previous cover files
   (rm /opt/data/music/artwork/covers/<ALBUM>_bg.png /opt/data/music/artwork/covers/<ALBUM>.png)
   and run gen_artwork.py again with a different --notes scene concept. Again,
   manually overlay the title.

4. **Copy to album directory** — Copy to /opt/data/music/artwork/albums/<album-name>/
   with distinct filenames (e.g. _titled.png and _titled_option2.png).

5. **Create Telegram previews** — ffmpeg downscale to 1500x1500 JPG for each option.

6. **Present both** — Send both previews to the user with descriptions, let them
   choose before uploading to SoundCloud.

## DESERT VOID Example

This session's example shows the pattern:

**Option 1 — "Car on Endless Asphalt"**
Scene: Matte-black muscle car on cracked desert highway under last-quarter moon.
Taillights bleeding red through heat haze. Dead Joshua trees, barbed wire fence.
Cinematic wide shot emphasizing the car's smallness against infinite void.

**Option 2 — "Fedora Figure, Desert Midnight"**
Scene: Mysterious figure in long coat and fedora standing alone on abandoned
desert highway, backlit by massive moon. Low-angle shot from ground level,
silver dust catching moonlight, lone red taillight in the far distance.

Both options used the real lunar phase for today (last quarter, 41% illuminated).

## Color / Text Treatment

- Title styled with Unicode: `ĐɆ₴ɆƦ† ⱴØłĐ`
- Overlay-title.py with --auto-color (automatically picked hyper magenta #FF007F
  for both — the dark desert backgrounds triggered the neon palette)
- Centered title (album cover, not track cover)
