---
name: unicode-track-titles
description: Stylize track titles using cool uncommon Unicode characters. Dark/electronic music aesthetic — selective character replacement that stays readable.
tags: [unicode, titles, track-naming, branding, creative]
---

# Unicode Track Title Stylizer

Convert plain track titles into stylized Unicode versions using uncommon characters that match the dark aesthetic.

## Character Reference Map

Keep this map of reliable, visually cool Unicode replacements:

| Plain | Unicode | Notes |
|-------|---------|-------|
| A/a | Δ/₳ | Delta or small ₳ |
| B/b | ฿ | Baht symbol |
| C/c | Ͼ/Ӿ | Coptic letters |
| D/d | Đ/đ | D with stroke |
| E/e | Ɇ/ɇ | E with stroke |
| F/f | ₣/₣ | Franc sign |
| G/g | Ǥ/ǥ | G with stroke |
| H/h | Ⱨ/Ⱨ | H with descender |
| I/i | ł/í | Dotless or accented |
| K/k |Ҟ/ҟ | Ka with stroke |
| L/l | Ⱡ/Ⱡ | L with bar |
| M/m | ӎ/ӎ | M with tail |
| N/n | ₦/₦ | Naira sign |
| O/o | Ø/ø | O with stroke (VØIDRIDE signature) |
| P/p | Ƥ/Ƥ | P with hook |
| Q/q | ɋ/ɋ | Q with hook tail |
| R/r | Ʀ/Ʀ | Yr/Replaces R |
| S/s | ₴/₴ | Lira sign |
| T/t | †/† | Dagger |
| U/u | Ʉ/Ʉ | U with bar |
| V/v | ⱴ/ⱴ | V with hook |
| W/w | ₩/₩ | Won sign |
| X/x | Ӿ/ӿ | Ha with stroke (NOT Greek chi χ) |
| Y/y | Ɏ/ɏ | Y with stroke (NOT ¥ Yen sign) |
| Z/z | ɀ/ɀ | Z with stroke |

## Style Rules

1. **Selective replacement** — don't replace EVERY letter. Mix caps, Unicode, and plain chars for readability
2. **Common substitutions that define the look:** Ø (not O), Δ (not A), ł (not I), Ʀ (not R), ฿ (not B), Ⱡ (not L), ₩ (not W)
3. **NOT just Δ/Ø** — use the full range of uncommon characters
4. **Stay readable** — if you can't read it as the original word, you've gone too far
5. **Dark aesthetic** — these should look like they belong on a metal album or witch house EP

## Examples

- Wraith Engine → ₩ƦΔł†Ⱨ Ɇ₦Ǥł₦ɇ
- Serpent Glide → ₴ɆƦƤɆ₦† ₲ⱠłĐɇ
- Hollow Frequency → ⱧØⱠⱠØ₩ ₣ƦɆɋɄɆ₦Ӿɏ
- Blacktop Ritual → ฿ⱠΔϾҞ†ØƤ Ʀł†ɄΔⱠ
- Offramp Requiem → Ø₣₣ƦΔӎƤ ƦɆɋɄłɆӎ

## Process

1. Take the plain English track title
2. Identify key/signature letters to replace (prioritize: Ø, Δ, ł, Ʀ, ฿, Ⱡ, ₩)
3. Replace remaining letters selectively — don't over-substitute
4. Verify readability: can you still sound out the original word?
## Code Point Reference for Batch Scripts

**CRITICAL: Always load `references/code-points.md` via `skill_view(name='unicode-track-titles', file_path='references/code-points.md')` BEFORE writing any Python script that constructs Unicode titles.** The SKILL.md table below is a quick visual reference only — the `references/code-points.md` file has the verified `\u` escape sequences for all characters including hard-to-find ones like X (Ӿ U+04FC, NOT Greek chi) and Y (Ɏ U+024E, NOT Yen sign ¥). Guessing code points from the table leads to wrong characters.

## VØIDRIDE Cover Art Context

When generating covers for VØIDRIDE tracks, the unicode track titles pair with per-track visual themes. Each track gets a unique car, lightning color, and neon accent.

**Title overlay:** Use the `cover-title-overlay` skill to render Unicode titles onto cover backgrounds. It handles Open Sans Bold font scaling, neon glow, drop shadow, and positioning. VØIDRIDE track covers (scene art) use `--bottom`; album covers (nebula) use default centering. Run:

```bash
# VØIDRIDE track cover (scene art — title at bottom)
python3 /opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py \
  --image track_bg.png --title "Ɇ₦†Ʀɏ₩ØɄ₦Đ" --color "#ff0044" --bottom

# Album cover (nebula — title centered)
python3 /opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py \
  --image album_bg.png --title "Ʉ₦ĐɆɌ₱Δ$$" --color "#ff8800"
```

**Always pull the Unicode title from the producer profile's catalog** — don't guess or reconstruct. Characters like Ɍ vs Ʀ and ៛ vs Ⱡ look similar but are different code points. The profile at `/opt/data/music/profiles/vidride/profile.json` has the canonical `catalog` list with exact Unicode titles.

See also `soundcloud/references/cover-art-generation.md` for the full cover art workflow (background generation, Venice API, SoundCloud upload). The `cover-title-overlay` skill has the VØIDRIDE track cover scene prompt pattern and per-track car/color mapping.