---
name: diagram-creation
description: "Create architecture and flow diagrams: dark-themed SVG infra diagrams (HTML) or hand-drawn Excalidraw JSON (arch, flow, seq)."
version: 2.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [diagrams, architecture, SVG, HTML, Excalidraw, visualization, infrastructure, flowchart, sequence]
    related_skills: [baoyu-infographic, p5js]
---

# Diagram Creation

Two visual styles for creating architecture and flow diagrams:

1. **Dark-themed SVG** — Professional dark aesthetic, HTML+SVG, grid background, semantic color palette. Best for tech/cloud infra.
2. **Hand-drawn Excalidraw** — Informal whiteboard aesthetic, JSON format. Best for quick sketches, flows, sequence diagrams.

## When to use

| Style | Best for | Output format |
|-------|----------|---------------|
| Dark SVG | Software architecture, cloud infra, microservice topology, deployment diagrams | Standalone `.html` file |
| Excalidraw | Flowcharts, sequence diagrams, wireframes, brainstorm sketches | `.excalidraw` JSON (opens in excalidraw.com) |

## Quick dispatch

- **Dark SVG diagrams** → See [Dark-themed SVG](#dark-themed-svg-diagrams) and `references/architecture-diagram.md`
- **Hand-drawn diagrams** → See [Excalidraw](#excalidraw-diagrams) and `references/excalidraw.md`

---

## Dark-themed SVG Diagrams

Generate professional, dark-themed technical architecture diagrams as standalone HTML files with inline SVG. No external tools, no API keys — just write the HTML and open in a browser.

### Color Palette (Semantic)

| Component Type | Fill | Stroke |
|:---|:---|:---|
| Frontend | `rgba(8,51,68,0.4)` | `#22d3ee` cyan |
| Backend | `rgba(6,78,59,0.4)` | `#34d399` emerald |
| Database | `rgba(76,29,149,0.4)` | `#a78bfa` violet |
| AWS/Cloud | `rgba(120,53,15,0.3)` | `#fbbf24` amber |
| Security | `rgba(136,19,55,0.4)` | `#fb7185` rose |
| Message Bus | `rgba(251,146,60,0.3)` | `#fb923c` orange |
| External | `rgba(30,41,59,0.5)` | `#94a3b8` slate |

### Key rules

- Components: rounded rects (`rx="6"`) with 1.5px strokes
- Double-rect masking to prevent arrows showing through transparent fills
- Z-order: draw arrows early so they render behind components
- Legend: MUST be placed outside all boundary boxes (≥20px below lowest boundary)
- Font: JetBrains Mono, 12px names / 9px sublabels

### Output

Single `.html` file, no JS, no external deps (except Google Fonts).

Full template and details → `references/architecture-diagram.md` + `templates/template.html`

---

## Excalidraw Diagrams

Create hand-drawn style diagrams using the Excalidraw JSON format. Opens in excalidraw.com or any Excalidraw-compatible editor.

### Supported diagram types

- Architecture diagrams (boxes and arrows)
- Flowcharts (decision diamonds, process boxes)
- Sequence diagrams (lifelines, messages, activations)
- Wireframes and brainstorm sketches

### Key rules

- Use the Excalidraw JSON schema for element definitions
- Elements: rectangles, diamonds, ellipses, arrows, text, lines
- Group related elements; use frames for sections
- Dark mode: `{"appState": {"theme": "dark"}}`

### Output

`.excalidraw` JSON file. Upload to excalidraw.com to view/edit.

Full schema and examples → `references/excalidraw.md`

---

## Choosing Between Styles

| Question | Answer → Style |
|----------|---------------|
| Is it tech/cloud infrastructure? | Dark SVG |
| Is it a quick brainstorm or wireframe? | Excalidraw |
| Does it need to look professional/presentable? | Dark SVG |
| Does it need collaborative editing? | Excalidraw |
| Is it a flowchart or sequence diagram? | Either — Excalidraw is faster |
| Does the user say "dark" / "professional" / "architecture"? | Dark SVG |
| Does the user say "hand-drawn" / "whiteboard" / "sketch"? | Excalidraw |
