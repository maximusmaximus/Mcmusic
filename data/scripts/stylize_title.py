#!/usr/bin/env python3
"""
Stylize plain track titles into VØIDRIDE Unicode aesthetic.
Selective replacement — not every letter, stays readable.

Usage:
    python3 stylize_title.py "EYEWALL"
    python3 stylize_title.py --all "EYEWALL,BLACKWATER,GLASSWAKE,FLOODLINE,CRESTFALL"
"""
import sys
import argparse

# Verified code points from references/code-points.md
UNICODE_MAP = {
    'A': '\u0394',  # Δ
    'B': '\u0e3f',  # ฿
    'C': '\u03fe',  # Ͼ
    'D': '\u0110',  # Đ
    'E': '\u0246',  # Ɇ
    'F': '\u20a3',  # ₣
    'G': '\u01e4',  # Ǥ
    'H': '\u2c67',  # Ⱨ
    'I': '\u0142',  # ł
    'K': '\u049e',  # Ҟ
    'L': '\u2c60',  # Ⱡ
    'M': '\u04ce',  # ӎ
    'N': '\u20a6',  # ₦
    'O': '\u00d8',  # Ø
    'P': '\u01a4',  # Ƥ
    'Q': '\u024b',  # ɋ
    'R': '\u01a6',  # Ʀ
    'S': '\u20a4',  # ₴
    'T': '\u2020',  # †
    'U': '\u0244',  # Ʉ
    'V': '\u2c74',  # ⱴ
    'W': '\u20a9',  # ₩
    'X': '\u04fc',  # Ӿ
    'Y': '\u024e',  # Ɏ
    'Z': '\u007a',  # ɀ
}

# Priority characters — always replace these
ALWAYS_REPLACE = set('OARDLWIBET')

# Secondary — replace about half the time for readability
SOMETIMES_REPLACE = set('CNGHSFKMPUVXYQZ')


def stylize(title):
    """Convert plain title to VØIDRIDE Unicode style."""
    result = []
    secondary_count = {}
    
    for ch in title.upper():
        if ch in ALWAYS_REPLACE and ch in UNICODE_MAP:
            result.append(UNICODE_MAP[ch])
        elif ch in SOMETIMES_REPLACE and ch in UNICODE_MAP:
            count = secondary_count.get(ch, 0)
            secondary_count[ch] = count + 1
            if count % 2 == 0:
                result.append(UNICODE_MAP[ch])
            else:
                result.append(ch)
        else:
            result.append(ch)
    
    return ''.join(result)


def main():
    parser = argparse.ArgumentParser(description="Stylize titles to VØIDRIDE Unicode")
    parser.add_argument("title", nargs="?", help="Single title to stylize")
    parser.add_argument("--all", help="Comma-separated list of titles")
    parser.add_argument("--json", action="store_true", help="Output as JSON mapping")
    args = parser.parse_args()
    
    if args.all:
        titles = [t.strip() for t in args.all.split(",")]
    elif args.title:
        titles = [args.title]
    else:
        print("Provide a title or --all", file=sys.stderr)
        sys.exit(1)
    
    if args.json:
        import json
        mapping = {t: stylize(t) for t in titles}
        print(json.dumps(mapping, ensure_ascii=False))
    else:
        for t in titles:
            styled = stylize(t)
            print(styled)


if __name__ == "__main__":
    main()
