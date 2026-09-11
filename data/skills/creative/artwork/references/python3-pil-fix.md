# Python3 PIL Fix — gen_artwork.py venv bug

## Problem

`gen_artwork.py` at `/opt/data/skills/artwork/artwork/scripts/gen_artwork.py` hardcodes `"python3"` (system Python) in its `overlay_title_on_cover()` function at line 324:

```python
cmd = [
    "python3",
    "/opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py",
    ...
]
```

System Python (`/usr/bin/python3`) does NOT have PIL installed. Running this step always crashes with:
```
ModuleNotFoundError: No module named 'PIL'
```

## Fix

The script should use `/opt/hermes/.venv/bin/python3` instead of `python3`. Until the script is patched, work around it by running the overlay step manually with the correct venv Python after gen_artwork.py finishes its background + upscale phases (which succeed via direct HTTP calls).

## References

- This file is referenced from the `cover-title-overlay` skill's pitfalls section
- The `artwork` skill covers the full pipeline with workaround instructions
- The `waveform-artwork` skill covers PIL-dependent waveform banner generation
