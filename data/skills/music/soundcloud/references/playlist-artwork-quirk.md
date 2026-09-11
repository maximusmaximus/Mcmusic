# Playlist Artwork Upload Quirk

## Problem

When uploading playlist artwork via `playlist[artwork_data]` multipart PUT, **JPG files sometimes return `artwork_url: null`** even when the file is small (tested with 1.4MB JPG). The upload request succeeds (200 OK) but the artwork URL in the response is null — meaning the artwork was silently rejected.

## Solution

**Use PNG format for playlist artwork.** In testing, a 9MB PNG succeeded where a 1.4MB JPG (of the same image) returned null.

For oversized PNGs (>10MB), downscale to 2000×2000 PNG before uploading:

```bash
ffmpeg -y -i cover.png -vf "scale=2000:2000:flags=lanczos" cover_2k.png
```

Then upload the 2K PNG via `playlist[artwork_data]`.

## Troubleshooting Steps

1. Try uploading the PNG directly (if under 10MB)
2. If PNG > 10MB, downscale to 2000×2000 PNG and retry
3. Only try JPG as a last resort — it may silently fail

## Note

This quirk affects **playlist** artwork specifically (`playlist[artwork_data]`). **Track** artwork uploads (`track[artwork_data]`) are more forgiving and handle both JPG and PNG reliably.

## Verification

After upload, check the `artwork_url` field in the response JSON. If it's `null`, the artwork was not saved — retry with a different format.