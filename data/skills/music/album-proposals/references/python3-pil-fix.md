# gen_artwork.py — System Python3 PIL Fix

## The Problem

gen_artwork.py's `overlay_title_on_cover()` function called `"python3"` as the interpreter
for overlay-title.py. The system Python3 (`/usr/bin/python3`) does NOT have Pillow (PIL)
installed — only the venv Python at `/opt/hermes/.venv/bin/python3` has it. Every run of
gen_artwork.py would:
1. Generate the background image successfully (up to the upscale step)
2. Fail at the title overlay step with `ModuleNotFoundError: No module named 'PIL'`

## The Fix

**Changed line 332** in gen_artwork.py from:
```python
cmd = ["python3", ...
```
to:
```python
cmd = ["/opt/hermes/.venv/bin/python3", ...
```

A `VENV_PYTHON` constant was also added at the top of the file for maintainability:
```python
VENV_PYTHON = "/opt/hermes/.venv/bin/python3"
```

## Verifying the Fix

After applying the fix, gen_artwork.py should complete the full workflow:
1. Generate background image (Venice API `grok-imagine-image-quality`, 1024x1024)
2. Upscale to 4K (Venice `/api/v1/image/upscale`, scale=4)
3. Crop waveform banner from clean background (may fail if no PIL or convert available)
4. Overlay stylized Unicode title (venv Python with PIL)

## If Still Failing

If the overlay step still fails, run it manually:
```bash
/opt/hermes/.venv/bin/python3 /opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py \
  --image /opt/data/music/artwork/covers/FILENAME_bg.png \
  --title "STYLED_TITLE" \
  --auto-color \
  --output /opt/data/music/artwork/covers/FILENAME.png
```

## Related

- `cover-title-overlay` skill — the overlay-title.py script and its documentation
- `artwork` skill SKILL.md — gen_artwork.py workflow, pitfalls, and full instructions
