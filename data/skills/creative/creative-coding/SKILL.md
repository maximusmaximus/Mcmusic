---
name: creative-coding
description: "Creative coding: p5.js sketches and Manim math/algorithm animations for visual art, generative graphics, and educational videos."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [creative-coding, generative-art, p5js, manim, animation, visualization, webgl, mathematical, educational]
    related_skills: [claude-design, comfyui, touchdesigner-mcp]
---

# Creative Coding: p5.js & Manim

Two creative coding platforms for generating visual artifacts from code:

- **p5.js** — Interactive and generative visual art in the browser. Sketches, data viz, shaders, particle systems, audio-reactive visuals. Single HTML file, no build step.
- **Manim** — Mathematical and algorithmic animations for educational videos. 3Blue1Brown-style explainers, equation visualizations, graph animations. Python-based, outputs MP4/GIF.

## When to Use

| User wants... | Use |
|---|---|
| Interactive browser-based generative art, data viz, particle systems, shader effects | p5.js |
| Mathematical animations, equation visualizations, educational explainers, algorithm visualizations | Manim |
| Both an interactive web version and a video export | Combine both — p5.js for exploration, Manim for polished video |

## p5.js (Interactive Generative Art)

Trigger when users request: p5.js sketches, generative art, interactive visualizations, canvas animations, creative coding, WebGL scenes, audio-reactive visuals, flow fields, particle systems, or browser-based visual art.

### Creative Standard

This is visual art rendered in the browser. The canvas is the medium; the algorithm is the brush.

**First-render excellence is non-negotiable.** The output must be visually striking on first load. If it looks like a tutorial exercise, it's wrong.

**Be proactively creative.** If the user asks for "a particle system," deliver one with emergent flocking behavior, trailing ghost echoes, palette-shifted depth fog, and a background noise field that breathes.

**Dense, layered, considered.** Every frame should reward viewing. Never flat white backgrounds. Always compositional hierarchy. Always intentional color.

### Modes

| Mode | Input | Output | Reference |
|------|-------|--------|-----------|
| Generative art | Seed / parameters | Procedural visual composition | `references/p5js/visual-effects.md` |
| Data visualization | Dataset / API | Interactive charts, custom displays | `references/p5js/interaction.md` |
| Interactive experience | User drives | Mouse/keyboard/touch-driven sketch | `references/p5js/interaction.md` |
| Animation / motion graphics | Timeline / storyboard | Timed sequences, kinetic typography | `references/p5js/animation.md` |
| 3D scene | Concept description | WebGL geometry, lighting, materials | `references/p5js/webgl-and-3d.md` |
| Image processing | Image file(s) | Pixel manipulation, filters, mosaic | `references/p5js/visual-effects.md` |
| Audio-reactive | Audio file / mic | Sound-driven generative visuals | `references/p5js/interaction.md` |

### Stack

Single self-contained HTML file per project. No build step.

| Layer | Tool | Purpose |
|-------|------|---------|
| Core | p5.js 1.11.3 (CDN) | Canvas rendering, math, events |
| 3D | p5.js WebGL mode | 3D geometry, GLSL shaders |
| Audio | p5.sound.js (CDN) | FFT analysis, amplitude |
| Export | `saveCanvas()` / `saveGif()` / `saveFrames()` | PNG, GIF, frames |
| Headless | Puppeteer + Node.js | Automated high-res rendering |
| Natural media | p5.brush (optional) | Watercolor, charcoal, pen |

Use p5.js 1.x (1.11.3) as default. Use 2.x only when p5.brush or other 2.x features are needed.

### Pipeline

```
CONCEPT → DESIGN → CODE → PREVIEW → EXPORT → VERIFY
```

### Per-Project Variation Rules

Never use default configurations:
- **Custom color palette** — never raw `fill(255, 0, 0)`
- **Custom stroke weight vocabulary** — thin accents (0.5), medium (1-2), bold (3-5)
- **Background treatment** — never plain `background(0)` or `background(255)`
- **Motion variety** — primary at 1x, secondary at 0.3x, ambient at 0.1x
- **At least one invented element** — novel particle behavior, unique interaction

### Key Implementation Patterns

- **Seeded randomness:** Always `randomSeed()` + `noiseSeed()` for reproducibility
- **Color mode:** Use `colorMode(HSB, 360, 100, 100, 100)` for intuitive control
- **Performance:** Disable FES (`p5.disableFriendlyErrors = true`), `pixelDensity(1)` in hot loops, `Math.*` instead of p5 wrappers
- **Offscreen buffers:** `createGraphics()` for layered composition, trails, masks
- **Instance mode:** For multiple sketches on one page or framework integration
- **WebGL origin:** Center, not top-left; Y-axis inverted

### Export

| Format | Method |
|--------|--------|
| PNG | `saveCanvas('output', 'png')` |
| GIF | `saveGif('output', 5)` |
| MP4 | Puppeteer frame capture + ffmpeg via `scripts/p5js/render.sh` |
| SVG | p5.js-svg `createCanvas(w, h, SVG)` |

### p5.js References

| File | Contents |
|------|----------|
| `references/p5js/core-api.md` | Canvas setup, coord system, draw loop, offscreen buffers |
| `references/p5js/shapes-and-geometry.md` | 2D primitives, curves, custom shapes, SDF |
| `references/p5js/visual-effects.md` | Noise, flow fields, particle systems, pixel manipulation |
| `references/p5js/animation.md` | Easing, spring physics, state machines, timelines |
| `references/p5js/typography.md` | `text()`, `loadFont()`, `textToPoints()`, kinetic type |
| `references/p5js/color-systems.md` | HSB/RGB, procedural palettes, blend modes |
| `references/p5js/webgl-and-3d.md` | 3D primitives, camera, lighting, GLSL shaders |
| `references/p5js/interaction.md` | Mouse, keyboard, touch, audio, scroll-driven |
| `references/p5js/export-pipeline.md` | Headless capture, ffmpeg, platform export |
| `references/p5js/troubleshooting.md` | Performance, common mistakes, browser compat |

### p5.js Scripts

| Script | Purpose |
|--------|---------|
| `scripts/p5js/render.sh` | Headless MP4 rendering via Puppeteer + ffmpeg |
| `scripts/p5js/serve.sh` | Local HTTP server for asset loading |
| `scripts/p5js/setup.sh` | Project scaffolding |
| `scripts/p5js/export-frames.js` | Deterministic frame capture |

---

## Manim (Mathematical Animation)

Trigger when users request: mathematical animations, educational videos, algorithm visualizations, equation animations, 3Blue1Brown-style explainers, Manim scenes, or graph/geometry animations.

### What Manim Gives You

Manim CE (Community Edition) renders mathematical and algorithmic animations as MP4/GIF. It excels at:
- Equation derivations step by step
- Graph and function animations
- Geometric proofs and constructions
- Data visualizations with narrative flow
- 3D scene exploration

### Workflow

1. **Plan the scene** — What mathematical/algorithmic concept? What visual narrative?
2. **Write the Python class** — Subclass `Scene`, define `construct()`
3. **Iterate** — Render with `manim -pql scene.py ClassName` (low quality for speed)
4. **Produce final** — `manim -qh scene.py ClassName` for high quality (1080p)
5. **Export** — MP4 by default; `--format gif` for GIF

### Core API Quick Reference

```python
from manim import *

class MyScene(Scene):
    def construct(self):
        # Text & equations
        title = Text("Hello Manim")
        eq = MathTex(r"E = mc^2")
        
        # Shapes
        circle = Circle(radius=1.5, color=BLUE)
        square = Square(side_length=2, color=RED)
        
        # Positioning
        circle.shift(LEFT * 2)
        square.next_to(circle, RIGHT, buff=0.5)
        
        # Animations
        self.play(Write(title))
        self.play(FadeIn(circle), FadeIn(square))
        self.play(circle.animate.set_fill(BLUE, opacity=0.5))
        self.play(Transform(circle, square))
        
        # Camera
        self.play(self.camera.frame.animate.move_to(circle))
```

### Key Animation Types

- **Creation:** `Write`, `Create`, `DrawBorderThenFill`, `AddTextLetterByLetter`
- **Fade:** `FadeIn`, `FadeOut`, `FadeInFrom`, `FadeOutAndShift`
- **Movement:** `Indicate`, `Flash`, `Circumscribe`, `Wiggle`
- **Transform:** `Transform`, `ReplacementTransform`, `TransformFromCopy`
- **Tracking:** `ValueTracker`, `always_redraw`, `Updater`
- **Grouping:** `VGroup`, `Arrange`, `arrange_in_grid`
- **Graphing:** `Axes`, `NumberPlane`, `plot`, `get_graph_label`
- **3D:** `ThreeDScene`, `Surface`, `Sphere`, `rotate`

### Production Tips

- Use `-pql` (low quality, 480p) for rapid iteration
- Use `-qh` (high quality, 1080p) for final output
- Use `-qk` (4K) only when needed
- Add `--format gif` for animated GIFs
- Use `self.wait()` between animation groups for pacing
- Break complex scenes into smaller classes

### Manim References

| File | Contents |
|------|----------|
| `references/manim/animations.md` | Complete animation reference (creation, movement, transform, etc.) |
| `references/manim/mobjects.md` | Mobject types, properties, methods |
| `references/manim/camera-and-3d.md` | Camera control, 3D scenes, rendering |
| `references/manim/decorations.md` | Styling, colors, backgrounds |
| `references/manim/equations.md` | Math typesetting, LaTeX, equation animations |
| `references/manim/graphs-and-data.md` | Plotting, axes, data visualization |
| `references/manim/updaters-and-trackers.md` | Dynamic updates, ValueTracker |
| `references/manim/rendering.md` | Output formats, quality, command-line flags |
| `references/manim/scene-planning.md` | Scene structure, narrative flow |
| `references/manim/visual-design.md` | Composition, color, typography |
| `references/manim/production-quality.md` | Polished output: timing, transitions, pacing |
| `references/manim/animation-design-thinking.md` | Conceptual design process |
| `references/manim/paper-explainer.md` | Academic paper visualization patterns |
| `references/manim/troubleshooting.md` | Common errors, LaTeX issues, rendering |

### Manim Scripts

| Script | Purpose |
|--------|---------|
| `scripts/manim/setup.sh` | Manim CE installation and dependency setup |

---

## Pitfalls

### p5.js
- **Disable FES** — `p5.disableFriendlyErrors = true` before `setup()`; 10x overhead without it
- **Seeded randomness always** — use `randomSeed()` + `noiseSeed()` for reproducibility
- **HSB color mode** — dramatically easier than RGB for generative palettes
- **Performance** — vectorize (`beginShape`/`POINTS`) for thousands of particles; pixel buffer for 50k+
- **WebGL origin** — center, not top-left; Y-axis inverted

### Manim
- **LaTeX required** — Manim needs a working LaTeX installation; install `texlive-full` or `texlive-latex-extra`
- **Render quality flags** — `-pql` for testing, `-pqh` for final; don't waste time rendering HD on every test
- **Scene class required** — every animation must be a `Scene` subclass with `construct()`
- **File naming** — class names must match the file for `manim` CLI to find them