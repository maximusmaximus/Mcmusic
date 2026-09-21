import json, urllib.request, base64, os, subprocess, time, sys

VENICE_API_KEY = os.environ.get("VENICE_API_KEY", "")
if not VENICE_API_KEY:
    print("No VENICE_API_KEY")
    sys.exit(1)

ARTWORK_DIR = "/opt/data/music/artwork/covers"
OUTPUT_DIR = "/opt/data/music/artwork/covers"
OVERLAY_SCRIPT = "/opt/data/skills/creative/cover-title-overlay/scripts/overlay-title.py"
VENV_PYTHON = "/opt/hermes/.venv/bin/python3"

# Unicode code points
U = {
    'R': '\u01a6', 'A': '\u0394', 'Z': '\u007a', 'O': '\u00d8', 'L': '\u2c60',
    'I': '\u0142', 'N': '\u20a6', 'E': '\u0246',
    'B': '\u0e3f', 'D': '\u0110', 'H': '\u2c67', 'T': '\u2020',
    'K': '\u049e', 'U': '\u0244', 'S': '\u20a4', 'C': '\u03fe',
    'V': '\u2c74', 'G': '\u01e4', 'P': '\u01a4'
}

def stylize(text):
    result = []
    for ch in text:
        upper = ch.upper()
        if upper in U:
            result.append(U[upper])
        else:
            result.append(ch)
    return ''.join(result)

tracks = [
    {
        "num": 1, "title": "RAZORLINE",
        "color": "#ff0044",
        "prompt": "Cyberpunk alley at midnight, a cybernetic ronin unsheathing a glowing crimson plasma katana, half-drawn blade casting red light on wet asphalt puddles, neon signs reflecting in rainwater, red lightning bolts striking in the distance, thick mist and fog, cinematic 35mm film photography, anamorphic lens flare, high contrast noir atmosphere, dark nightride aesthetic. NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS, NO SYMBOLS, NO TYPOGRAPHY, NO FONTS, NO WATERMARKS, NO LABELS, NO SIGNS, NO CAPTIONS."
    },
    {
        "num": 2, "title": "BLOOD SHEATH",
        "color": "#cc0000",
        "prompt": "Dark rain-slicked alley close-up, a katana scabbard dripping with viscous blood-like fluid, crimson neon glow reflecting off the wet surface, steam rising from warm blood on cold pavement, dark shadows, moody atmospheric lighting, cinematic 35mm film grain, high contrast, blood-red color grading. NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS, NO SYMBOLS, NO TYPOGRAPHY, NO FONTS, NO WATERMARKS, NO LABELS, NO SIGNS, NO CAPTIONS."
    },
    {
        "num": 3, "title": "NUKITSUKE",
        "color": "#00ccff",
        "prompt": "Dynamic action shot in a rain-slicked cyberpunk alley, lightning-fast iaido sword draw, plasma katana blade glowing intense ice-blue leaving a frozen light trail mid-swing, water droplets suspended in air catching the blue glow, motion blur, the ronin's silhouette in a split-second combat stance, cinematic 35mm film photography, anamorphic lens flare, high speed frozen moment. NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS, NO SYMBOLS, NO TYPOGRAPHY, NO FONTS, NO WATERMARKS, NO LABELS, NO SIGNS, NO CAPTIONS."
    },
    {
        "num": 4, "title": "CARBON SCABBARD",
        "color": "#ff8800",
        "prompt": "Low-angle shot in an industrial alley, a carbon fiber katana scabbard lying on wet cracked concrete, amber utility lights casting long dramatic shadows, mechanical gears and industrial pipes in the background, steam vents, dark brutalist architecture, cinematic 35mm film photography, warm amber highlights on carbon fiber texture, noir atmosphere. NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS, NO SYMBOLS, NO TYPOGRAPHY, NO FONTS, NO WATERMARKS, NO LABELS, NO SIGNS, NO CAPTIONS."
    },
    {
        "num": 5, "title": "SHADOW SEVER",
        "color": "#aa00ff",
        "prompt": "Wide cinematic shot of a rain-slicked alley, the cybernetic ronin standing as a dark silhouette with a fully-drawn plasma katana glowing intense purple, thick mist and fog swirling around, purple neon signs reflecting in puddles, distant lightning, the final moment before the strike, epic cinematic composition, anamorphic lens flare, 35mm film grain, dark atmospheric night mood. NO TEXT, NO LETTERS, NO CHARACTERS, NO WORDS, NO WRITING, NO NUMBERS, NO SYMBOLS, NO TYPOGRAPHY, NO FONTS, NO WATERMARKS, NO LABELS, NO SIGNS, NO CAPTIONS."
    }
]

for t in tracks:
    n = t["num"]
    title = t["title"]
    color = t["color"]
    prompt = t["prompt"]
    
    slug = title.lower().replace(" ", "_")
    raw_file = f"{ARTWORK_DIR}/katana_{n}_{slug}_raw.png"
    bg_file = f"{ARTWORK_DIR}/katana_{n}_{slug}_bg.png"
    cover_file = f"{ARTWORK_DIR}/katana_{n}_{slug}_cover.png"
    jpg_file = f"{ARTWORK_DIR}/katana_{n}_{slug}_cover.jpg"
    
    # Unicode title
    unicode_title = stylize(title)
    
    print(f"[{n}/5] {title} → {unicode_title} ({color})")
    
    # Step 1: Generate background
    payload = json.dumps({
        "model": "flux-2-max",
        "prompt": prompt,
        "width": 1024,
        "height": 1024
    }).encode()
    
    req = urllib.request.Request(
        "https://api.venice.ai/api/v1/image/generate",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {VENICE_API_KEY}"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
    except Exception as e:
        print(f"  ❌ API error: {e}")
        continue
    
    images = result.get("images", [])
    if not images:
        print(f"  ❌ No images returned")
        continue
    
    with open(raw_file, "wb") as f:
        f.write(base64.b64decode(images[0]))
    
    size_kb = os.path.getsize(raw_file) / 1024
    if size_kb < 10:
        print(f"  ❌ Image too small ({size_kb:.0f}KB), retrying...")
        time.sleep(3)
        # Retry once
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())
            images = result.get("images", [])
            if images:
                with open(raw_file, "wb") as f:
                    f.write(base64.b64decode(images[0]))
        except:
            pass
    
    # Step 2: Upscale
    subprocess.run([
        "ffmpeg", "-y", "-i", raw_file,
        "-vf", "scale=3000:3000:flags=lanczos,unsharp=5:5:0.8:5:5:0",
        bg_file
    ], capture_output=True)
    print(f"  ✅ Background generated + upscaled ({os.path.getsize(bg_file)/1024:.0f}KB)")
    
    # Step 3: Overlay title
    result = subprocess.run([
        VENV_PYTHON, OVERLAY_SCRIPT,
        "--image", bg_file,
        "--title", unicode_title,
        "--color", color,
        "--output", cover_file,
        "--bottom"
    ], capture_output=True, text=True)
    print(f"  ✅ Cover: {cover_file} ({result.stdout.strip()})")
    
    # Step 4: Create JPG preview
    subprocess.run([
        "ffmpeg", "-y", "-i", cover_file,
        "-vf", "scale=1500:1500:flags=lanczos", "-q:v", "2",
        jpg_file
    ], capture_output=True)
    print(f"  ✅ JPG preview created")
    
    # Small delay between tracks
    time.sleep(2)

print("\n=== ALL COVERS COMPLETE ===")
