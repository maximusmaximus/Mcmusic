# Unicode Code Point Reference for Batch Script Generation

When writing Python batch scripts that construct Unicode track titles, use these
exact code points. Visual characters are unreliable in inline Python — always
build strings from `\u` escape sequences in file-based scripts.

## Verified Code Points (Uppercase)

| Letter | Character | Code Point | Unicode Name |
|--------|-----------|------------|--------------|
| A | Δ | U+0394 | GREEK CAPITAL LETTER DELTA |
| B | ฿ | U+0E3F | THAI CURRENCY SYMBOL BAHT |
| C | Ͼ | U+03FE | GREEK CAPITAL REVERSED DOTTED LUNATE SIGMA SYMBOL |
| D | Đ | U+0110 | LATIN CAPITAL LETTER D WITH STROKE |
| E | Ɇ | U+0246 | LATIN CAPITAL LETTER E WITH STROKE |
| F | ₣ | U+20A3 | FRENCH FRANC SIGN |
| G | Ǥ | U+01E4 | LATIN CAPITAL LETTER G WITH STROKE |
| H | Ⱨ | U+2C67 | LATIN CAPITAL LETTER H WITH DESCENDER |
| I | ł | U+0142 | LATIN SMALL LETTER L WITH STROKE |
| K | Ҟ | U+049E | CYRILLIC CAPITAL LETTER KA WITH STROKE |
| L | Ⱡ | U+2C60 | LATIN CAPITAL LETTER L WITH DOUBLE BAR |
| M | ӎ | U+04CE | CYRILLIC SMALL LETTER EM WITH TAIL |
| N | ₦ | U+20A6 | NAIRA SIGN |
| O | Ø | U+00D8 | LATIN CAPITAL LETTER O WITH STROKE |
| P | Ƥ | U+01A4 | LATIN CAPITAL LETTER P WITH HOOK |
| Q | ɋ | U+024B | LATIN SMALL LETTER Q WITH HOOK TAIL |
| R | Ʀ | U+01A6 | LATIN LETTER YR |
| S | ₴ | U+20A4 | LIRA SIGN |
| T | † | U+2020 | DAGGER |
| U | Ʉ | U+0244 | LATIN CAPITAL LETTER U WITH STROKE |
| V | ⱴ | U+2C74 | LATIN SMALL LETTER V WITH CURL |
| W | ₩ | U+20A9 | WON SIGN |
| X | Ӿ | U+04FC | CYRILLIC CAPITAL LETTER HA WITH STROKE |
| Y | Ɏ | U+024E | LATIN CAPITAL LETTER Y WITH STROKE |
| Z | ɀ | U+007A | LATIN SMALL LETTER Z WITH STROKE |

## Verified Code Points (Lowercase)

| Letter | Character | Code Point | Unicode Name |
|--------|-----------|------------|--------------|
| e | ɇ | U+0247 | LATIN SMALL LETTER E WITH STROKE |

## Python Usage

```python
# Build titles from code points in batch scripts
T_M = "\u04ce"  # ӎ
T_I = "\u0142"  # ł
T_D = "\u0110"  # Đ
T_N = "\u20a6"  # ₦
T_G = "\u01e4"  # Ǥ
T_H = "\u2c67"  # Ⱨ
T_T = "\u2020"  # †
T_R = "\u01a6"  # Ʀ
T_A = "\u0394"  # Δ
T_L = "\u2c60"  # Ⱡ
T_S = "\u20a4"  # ₴
T_O = "\u00d8"  # Ø
T_W = "\u20a9"  # ₩
T_C = "\u03fe"  # Ͼ
T_E = "\u0246"  # Ɇ
T_e = "\u0247"  # ɇ
T_P = "\u01a4"  # Ƥ
T_U = "\u0244"  # Ʉ
T_K = "\u049e"  # Ҟ
T_B = "\u0e3f"  # ฿
T_V = "\u2c74"  # ⱴ
T_X = "\u04fc"  # Ӿ (Cyrillic Capital Letter Ha With Stroke — NOT Greek chi χ)
T_Y = "\u024e"  # Ɏ (Latin Capital Letter Y With Stroke — NOT ¥ Yen sign)
T_F = "\u20a3"  # ₣
T_Q = "\u024b"  # ɋ
T_Z = "\u007a"  # ɀ
T_a = "\u0394"  # Δ (same as uppercase A in VØIDRIDE style)
T_d = "\u0110"  # đ (lowercase D with stroke)

# Example: MIDNIGHT RADIAL
title = T_M + T_I + T_D + T_N + T_I + T_G + T_H + T_T + " " + T_R + T_A + T_D + T_I + T_A + T_L
# Result: ӎłĐ₦łǤⱧ† ƦΔĐłΔⱠ

# Example: HEX CODE (uses X = Ӿ, not Greek chi χ)
title_hex = T_H + T_E + T_X + " " + T_C + T_O + T_D + T_E
# Result: ⱧɆӾ ϾØĐɆ

# Example: SYNTHETIC RITE (uses Y = Ɏ, not ¥ Yen sign)
title_synth = T_S + T_Y + T_N + T_T + T_H + T_E + T_T + T_I + T_C + " " + T_R + T_I + T_T + T_E
# Result: ₴Ɏ₦†ⱧɆ†łϾ Ʀł†Ɇ
```

## Common Pitfalls

- **R vs Ʀ** — U+01A6 (Ʀ, LATIN LETTER YR) is the correct code point. Do NOT confuse with U+01A2 (ophiucus) or other similar-looking characters.
- **Ⱡ vs other L variants** — U+2C60 (Ⱡ, L WITH DOUBLE BAR) is correct. U+004C is plain L.
- **Case sensitivity** — most VØIDRIDE titles use uppercase Unicode replacements for all letters. Lowercase variants exist for some letters (e.g. ɇ for e) but are rarely needed.
- **X ≠ Greek chi** — Use Ӿ (U+04FC, Cyrillic Capital Letter Ha With Stroke). Do NOT use χ (U+03C7, Greek Small Letter Chi) — it looks similar but is a different script entirely and renders inconsistently in Open Sans Bold.
- **Y ≠ Yen sign** — Use Ɏ (U+024E, Latin Capital Letter Y With Stroke). Do NOT use ¥ (U+00A5, Yen Sign) — it's a currency symbol, not a letter, and looks wrong in titles.
- **Always write to file** — inline `python3 -c '...'` commands can mangle Unicode. Write batch scripts to `.py` files and run via `terminal()`.
- **ALWAYS load this reference file first** — Before building any Python cover generation script, call `skill_view(name='unicode-track-titles', file_path='references/code-points.md')` to get the current code points. Do not guess from the SKILL.md table alone — the reference file has the verified `\u` escape sequences.
