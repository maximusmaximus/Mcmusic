# Album Upload Workflow

Full end-to-end workflow for publishing a produced album to SoundCloud with cover art, per-track metadata, and tag fix-up pass.

## Step 0: Generate Cover Art (Prerequisite)

Before uploading, each track needs cover art (800×800 minimum, PNG/JPEG). Generate covers using the Venice Image API (ideogram-v4) and overlay neon Unicode titles with PIL. See the `master-producer` skill → `references/cover-art.md` for the full generation + overlay workflow.

**Quick summary:**
1. Generate base artwork with ideogram-v4 (`aspect_ratio: "1:1"`, `return_binary: false`)
2. Convert WebP → PNG with ffmpeg
3. Overlay neon Unicode titles with PIL (Open Sans Bold, fill ~92% width, max saturation colors, angled drop shadow)
4. Save as `{NN}_TRACK_NAME_titled.png`

The cover generation script must be written to a file and run via `terminal()` (not `execute_code`) — the sandbox doesn't have access to the `VENICE_API_KEY` environment variable.

## Step 1: Convert WAV Masters to MP3

SoundCloud re-encodes everything. FLAC offers no quality advantage and uploads 5x slower. Convert to 320k MP3:

```bash
mkdir -p /opt/data/music/productions/ALBUM_NAME
for i in $(seq 1 N); do
  ffmpeg -y -i "$WAV_PATH" -b:a 320k -map_metadata -1 "$MP3_PATH" 2>/dev/null
done
```

`-map_metadata -1` clears source metadata so SoundCloud uses what you provide via API.

## Step 2: Upload All Tracks (Python Script)

Write a Python script with `write_file`, then run via `terminal` with `background=true` and `notify_on_complete=true`. The script calls `soundcloud_api.py upload` per track.

**Why a Python script instead of `batch-upload`?** The `batch-upload` command matches artwork by filename stem, which works for simple naming but not when tracks have Unicode titles or custom per-track descriptions. A Python script gives full control over per-track titles, descriptions, tags, and artwork paths.

### Proven Template

```python
#!/usr/bin/env python3
"""Album upload script — run via terminal, not execute_code."""
import subprocess, json, time

SC = "/opt/data/skills/music/soundcloud/scripts/soundcloud_api.py"

TRACKS = [
    {
        "file": "/path/to/track1.mp3",
        "artwork": "/path/to/covers/01_cover.png",
        "title": "ARTIST — TRACK TITLE",
        "description": "Genre description. BPM, key.\n\nProduction notes.\nMixed & mastered at -14 LUFS",
        "tags": "genre,genre2,bpm,key,album_name",
    },
    # ... more tracks
]

track_ids = []

for i, track in enumerate(TRACKS):
    print(f"\n=== Uploading {i+1}/{len(TRACKS)}: {track['title']} ===")

    cmd = [
        "python3", SC, "upload",
        "--file", track["file"],
        "--artwork", track["artwork"],
        "--title", track["title"],
        "--description", track["description"],
        "--tags", track["tags"],
        "--genre", "Electronic",
        "--sharing", "public",
        "--downloadable"
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode == 0:
        output = result.stdout.strip()
        print(f"  Output: {output[-300:]}")

        # Extract track ID from JSON response
        # The response contains the full track object with "id" field
        # Try parsing the last few lines which usually contain the JSON
        for line in reversed(output.split('\n')):
            line = line.strip()
            if line.startswith('{'):
                try:
                    data = json.loads(line)
                    tid = data.get('id')
                    if tid:
                        track_ids.append(tid)
                        print(f"  Track ID: {tid}")
                        break
                except json.JSONDecodeError:
                    pass

        print(f"  ✓ Upload complete")
    else:
        print(f"  ✗ Upload failed!")
        print(f"  STDERR: {result.stderr[-300:]}")

    if i < len(TRACKS) - 1:
        time.sleep(3)  # Rate limit spacing between uploads

print(f"\nCollected track IDs: {track_ids}")
```

### Key Points
- Use 3-second delays between uploads to avoid rate limiting
- 320k MP3 files (~8MB for 3:30) upload in ~30-60 seconds each
- Collect track IDs from JSON response for the tag update pass
- The `--downloadable` flag makes tracks available for download

## Step 3: Tag Update Pass (Critical)

Tags often do not stick on initial upload. After all uploads complete, run a second pass:

```python
for i, (tid, track) in enumerate(zip(track_ids, TRACKS)):
    print(f"  Updating tags for track {tid}: {track['title']}")
    cmd = ["python3", SC, "update", "--track-id", str(tid), "--tags", track["tags"]]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode == 0:
        print(f"  ✓ Tags updated")
    else:
        print(f"  ✗ Tags update failed: {result.stderr[-200:]}")
    time.sleep(2)
```

### Tags Format
- Comma-separated in the `--tags` argument (script converts to SC format internally)
- Include genre, subgenre, mood, BPM, key, and album name
- Example: `"witch house,dark trap,nightride,bass,152bpm,f minor,voidlines"`

## Step 4: Enriched Description Update (Optional)

For creative/personality content in descriptions (poems, lore, album context), add it in a separate update pass after the initial upload. This separates the technical description from the creative content and makes it easier to edit one without touching the other.

```python
for i, (tid, track) in enumerate(zip(track_ids, TRACKS)):
    full_desc = track["technical_desc"] + "\n\n" + track["creative_content"]
    cmd = ["python3", SC, "update", "--track-id", str(tid), "--description", full_desc]
    subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    time.sleep(2)
```

## Step 5: Update Cover Art on Existing Tracks (If Needed)

If you need to change a track's cover art after upload (e.g., you regenerated covers):

```bash
python3 /opt/data/skills/music/soundcloud/scripts/soundcloud_api.py \
  update --track-id 2377094909 --artwork /path/to/new_cover.png
```

## Step 6: Verify

```bash
python3 /opt/data/skills/music/soundcloud/scripts/soundcloud_api.py list --limit 15 --json
```

Check all tracks show `sharing: public` and correct titles. Permalink URLs will mangle Unicode — use `track_id` for API operations.

## Timing Estimates

| Step | 5-track Album |
|------|--------------|
| Convert WAV to MP3 | ~15 seconds |
| Upload 5 tracks (8MB each) | ~5-7 minutes |
| Tag update pass | ~15 seconds |
| Description enrichment | ~15 seconds |
| **Total** | **~6-8 minutes** |

## Common Unicode Permalink Mangles

SoundCloud strips or transliterates Unicode in permalink URLs. These are cosmetic only — display titles are correct:

| Display Title | Permalink Slug |
|--------------|----------------|
| `VØIDRIDE — ΣCHO DRIFT` | `v-idride-scho-drift` |
| `VØIDRIDE — FROZEN MΞRIDIAN` | `v-idride-frozen-mxridian` |
| `VØIDRIDE — VOID FRΣQUENCY` | `v-idride-void-frsquency` |
| `VØIDRIDE — GRΔVESHIFT` | `v-idride-grdveshift` |
| `VØIDRIDE — HΔDES DRIFT` | `v-idride-hddes-drift` |

Use `track_id` (numeric) for all API operations. Share permalink URLs with users since they still work despite mangling.

### Track ID Extraction

When running the upload script via `subprocess.run()`, the `soundcloud_api.py` JSON output uses `"track_id"` as the field name (not `"id"`). Extract accordingly:

```python
data = json.loads(result.stdout)
tid = data.get("track_id")  # NOT data.get("id")
```

If `track_ids` is empty after uploads, fall back to listing:
1. Run `soundcloud_api.py list --limit N` (where N = number of tracks just uploaded)
2. Match tracks by title to find their IDs
3. Use those IDs for the tag update and artwork passes

## Cannot Replace Audio on Existing Tracks

SoundCloud's API has **no endpoint to replace audio** on an existing track. If you need to fix audio (e.g., remastered version, missing stem restored):

1. Upload the new audio as a **new track** with "(Remastered)" in the title
2. Update the **old** track's description with a link to the new version: `"⚠️ SUPERSEDED — Listen to the remastered version: https://soundcloud.com/user/permalink"`
3. Keep both tracks public (don't delete the old one — it may have plays/stats)

There is no `delete` command in `soundcloud_api.py` — only `upload`, `update`, `list`, `status`, and `batch-upload`.