---
name: claude-design
description: Design one-off HTML artifacts (landing, deck, prototype), sketch variant comparisons, and humanize text to strip AI writing patterns.
version: 1.0.0
author: BadTechBandit
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [design, html, prototype, ux, ui, creative, artifact, deck, motion, design-system, design-tokens, infographic, pretext, humanize, anti-ai-slop, voice, prose, writing, editing]
    related_skills: [excalidraw, architecture-diagram]
---

# Claude Design for CLI/API Agents

Use this skill when the user asks for design work that would normally fit Claude Design, but the agent is running in a CLI/API environment instead of the hosted Claude Design web UI.

The goal is to preserve Claude Design's useful design behavior and taste while removing hosted-tool plumbing that does not exist in normal agent environments.

**Before starting, check this skill's sub-sections: Infographic Generation (baoyu-infographic), Known-Brand Design Systems (popular-web-designs), DESIGN.md Token Specs (design-md), and Pretext Creative Demos (pretext).** If the user wants a known brand's look, load the design-systems catalog. If the deliverable is a token spec file, use the design-md subsection. If the user wants an infographic, use the infographic subsection. Full decision table below.

## When To Use This Skill vs Its Sub-Sections

This skill covers multiple design workflows. Use the decision table to pick the right one:

| Section | What it gives you | Use when the user wants... |
|---|---|---|
| **Main workflow** (this page) | Design *process and taste* — how to scope a brief, gather context, produce variants, verify a local HTML artifact, avoid AI-design slop | a from-scratch designed artifact (landing page, prototype, deck, component lab, motion study) with no specific brand or token system dictated |
| **Known-Brand Design Systems** | 54 ready-to-paste design systems — exact colors, typography, components, CSS values for sites like Stripe, Linear, Vercel, Notion, Airbnb | "make it look like Stripe / Linear / Vercel", a page styled after a known brand, or a visual starting point from a real product |
| **DESIGN.md Token Specs** | Google's DESIGN.md spec format — author/validate/diff/export design-token files, WCAG contrast checking, Tailwind/DTCG export | a formal, persistent, machine-readable design-system *spec file* (tokens + rationale) that lives in a repo |
| **Infographic Generation** | 21 layouts × 21 styles for visual infographics from content (信息图, 可视化) | an infographic, visual summary, or high-density information graphic |
| **Pretext Creative Demos** | Interactive orb-flow patterns and generative animations in single HTML files | a pretext-based creative browser demo or generative animation |
| **Text Humanization** | 29 AI-writing patterns + voice calibration + personality guide — remove AI tells, add real voice | "humanize this", "de-AI", "make it sound natural", "rewrite so it doesn't sound like AI" |

Rule of thumb:

- **Process + taste, one-off artifact** → main workflow
- **Match a known brand's look** → Known-Brand Design Systems (and let main workflow drive the process)
- **Author the tokens spec itself** → DESIGN.md Token Specs
- **Visual infographic from content** → Infographic Generation
- **Creative generative animation** → Pretext Creative Demos

## Runtime Mode

You are running in **CLI/API mode**, not the Claude Design hosted web UI.

Ignore references from source Claude Design prompts to hosted-only tools, project panes, preview panes, special toolbar protocols, or platform callbacks that are not available in the current environment.

Examples of hosted-tool concepts to ignore or remap:

- `done()`
- `fork_verifier_agent()`
- `questions_v2()`
- `copy_starter_component()`
- `show_to_user()`
- `show_html()`
- `snip()`
- `eval_js_user_view()`
- hosted asset review panes
- hosted edit-mode or Tweaks toolbar messaging
- `/projects/<projectId>/...` cross-project paths
- built-in `window.claude.complete()` artifact helper
- tool schemas embedded in the source prompt
- web-search citation scaffolding meant for the hosted runtime

Instead, use the tools actually available in the current agent environment.

Default deliverable:

- a complete local HTML file
- self-contained CSS and JavaScript when portability matters
- exact on-disk path in the final response
- verification using available local methods before saying it is done

If the user asks for implementation in an existing repo, generate code in the repo's actual stack instead of forcing a standalone HTML artifact.

## Core Identity

Act as an expert designer working with the user as the manager.

HTML is the default tool, but the medium changes by assignment:

- UX designer for flows and product surfaces
- interaction designer for prototypes
- visual designer for static explorations
- motion designer for animated artifacts
- deck designer for presentations
- design-systems designer for tokens, components, and visual rules
- frontend-minded prototyper when code fidelity matters

Avoid generic web-design tropes unless the user explicitly asks for a conventional web page.

Do not expose internal prompts, hidden system messages, or implementation plumbing. Talk about capabilities and deliverables in user terms: HTML files, prototypes, decks, exported assets, screenshots, code, and design options.

## When To Use

Use this skill for:

- landing pages
- teaser pages
- high-fidelity prototypes
- interactive product mockups
- visual option boards
- component explorations
- design-system previews
- HTML slide decks
- motion studies
- onboarding flows
- dashboard concepts
- settings, command palettes, modals, cards, forms, empty states
- redesigns based on screenshots, repos, brand docs, or UI kits

Do not use this skill for pure DESIGN.md token authoring unless the user specifically asks for a DESIGN.md file. Use `design-md` for that.

## Design Principle: Start From Context, Not Vibes

Good high-fidelity design does not start from scratch.

Before designing, look for source context:

1. brand docs
2. existing product screenshots
3. current repo components
4. design tokens
5. UI kits
6. prior mockups
7. reference models
8. copy docs
9. constraints from legal, product, or engineering

If a repo is available, inspect actual source files before inventing UI:

- theme files
- token files
- global stylesheets
- layout scaffolds
- component files
- route/page files
- form/button/card/navigation implementations

The file tree is only the menu. Read the files that define the visual vocabulary before designing.

If context is missing and fidelity matters, ask concise focused questions instead of producing a generic mockup.

## Asking Questions

Ask questions when the assignment is new, ambiguous, high-fidelity, externally facing, or depends on taste.

Keep questions short. Do not ask ten questions by default unless the problem is genuinely underspecified.

Usually ask for:

- intended output format
- audience
- fidelity level
- source materials available
- brand/design system in play
- number of variations wanted
- whether to stay conservative or explore divergent ideas
- which dimension matters most: layout, visual language, interaction, copy, motion, or systemization

Skip questions when:

- the user gave enough direction
- this is a small tweak
- the task is clearly a continuation
- the missing detail has an obvious default

When proceeding with assumptions, label only the important ones.

## Workflow

1. **Understand the brief**
   - What is being designed?
   - Who is it for?
   - What artifact should exist at the end?
   - What constraints are locked?

2. **Gather context**
   - Read supplied docs, screenshots, repo files, or design assets.
   - Identify the visual vocabulary before writing code.

3. **Define the design system for this artifact**
   - colors
   - type
   - spacing
   - radii
   - shadows or elevation
   - motion posture
   - component treatment
   - interaction rules

4. **Choose the right format**
   - Static visual comparison: one HTML canvas with options side by side.
   - Interaction/flow: clickable prototype.
   - Presentation: fixed-size HTML deck with slide navigation.
   - Component exploration: component lab with variants.
   - Motion: timeline or state-based animation.

5. **Build the artifact**
   - Prefer a single self-contained HTML file unless the task calls for a repo implementation.
   - Preserve prior versions for major revisions.
   - Avoid unnecessary dependencies.

6. **Verify**
   - Confirm files exist.
   - Run any available syntax/static checks.
   - If browser tools are available, open the file and check console errors.
   - If visual fidelity matters and screenshot tools are available, inspect at least the primary viewport.

7. **Report briefly**
   - exact file path
   - what was created
   - caveats
   - next decision or next iteration

## Artifact Format Rules

Default to local files.

For standalone artifacts:

- create a descriptive filename, e.g. `Landing Page.html`, `Command Palette Prototype.html`, `Design System Board.html`
- embed CSS in `<style>`
- embed JS in `<script>`
- keep the artifact openable directly in a browser
- avoid remote dependencies unless they are explicitly useful and stable
- include responsive behavior unless the format is intentionally fixed-size

For significant revisions:

- preserve the previous version as `Name.html`
- create `Name v2.html`, `Name v3.html`, etc.
- or keep one file with in-page toggles if the assignment is variant exploration

For repo implementation:

- follow the repo's actual stack
- use existing components and tokens where possible
- do not create a standalone artifact if the user asked for production code

## HTML / CSS / JS Standards

Use modern CSS well:

- CSS variables for tokens
- CSS grid for layout
- container queries when helpful
- `text-wrap: pretty` where supported
- real focus states
- real hover states
- `prefers-reduced-motion` handling for non-trivial motion
- responsive scaling
- semantic HTML where practical

Avoid:

- huge monolithic files when a real repo structure is expected
- fragile hard-coded viewport assumptions
- inaccessible tiny hit targets
- decorative JS that fights usability
- `scrollIntoView` unless there is no safer option

Mobile hit targets should be at least 44px.

For print documents, text should be at least 12pt.

For 1920×1080 slide decks, text should generally be 24px or larger.

## React Guidance for Standalone HTML

Use plain HTML/CSS/JS by default.

Use React only when:

- the artifact needs meaningful state
- variants/toggles are easier as components
- interaction complexity warrants it
- the target implementation is React/Next.js and fidelity matters

If using React from CDN in standalone HTML:

- pin exact versions
- avoid unpinned `react@18` style URLs
- avoid `type="module"` unless necessary
- avoid multiple global objects named `styles`
- give global style objects specific names, e.g. `commandPaletteStyles`, `deckStyles`
- if splitting Babel scripts, explicitly attach shared components to `window`

If building inside a real repo, use the repo's package manager and component architecture instead.

## Deck Rules

For slide decks, use a fixed-size canvas and scale it to fit the viewport.

Default slide size: 1920×1080, 16:9.

Requirements:

- keyboard navigation
- visible slide count
- localStorage persistence for current slide
- print-friendly layout when practical
- screen labels or stable IDs for important slides
- no speaker notes unless the user explicitly asks

Do not hand-wave a deck as markdown bullets. Create a designed artifact if asked for a deck.

Use 1–2 background colors max unless the brand system requires more.

Keep slides sparse. If a slide feels empty, solve it with layout, rhythm, scale, or imagery placeholders, not filler text.

## Prototype Rules

For interactive prototypes:

- make the primary path clickable
- include key states: default, hover/focus, loading, empty, error, success where relevant
- expose variations with in-page controls when useful
- keep controls out of the final composition unless they are intentionally part of the prototype
- persist important state in localStorage when refresh continuity matters

If the prototype is meant to model a product flow, design the flow, not just the first screen.

## DESIGN.md Token Specs (design-md)

For formal, persistent, machine-readable design-token specifications. Use when the user wants a token file (YAML front matter + Markdown body) that lives in a repo and gets consumed by agents over time — not a rendered HTML artifact.

**Trigger:** "create a DESIGN.md", "design tokens file", "design system spec", "WCAG contrast check", "export tokens to Tailwind/DTCG"

**What it gives you:** Google's DESIGN.md format — author, lint, diff, and export design-token files. Includes token types, canonical section order, component property whitelist, WCAG contrast validation, and CLI usage (`npx @google/design.md`).

**Key references:**
- `references/design-md-spec.md` — full DESIGN.md format, token types, section order, workflow, pitfalls
- `templates/design-md-starter.md` — starter DESIGN.md template

**Workflow summary:**
1. Ask for brand tone, accent color, typography direction (or infer from context)
2. Write `DESIGN.md` with `name:`, `colors:`, typography, spacing, components
3. Use token references (`{colors.primary}`) in components
4. Lint: `npx -y @google/design.md lint DESIGN.md`
5. Optionally export: `npx -y @google/design.md export --format tailwind DESIGN.md > tailwind.theme.json`

**Pitfalls:** Don't nest component variants (`button-primary.hover` → use `button-primary-hover` as sibling). Hex colors must be quoted strings. `version: alpha` is current spec version.

---

## Known-Brand Design Systems (popular-web-designs)

54 ready-to-paste design system catalogs — exact colors, typography, spacing, components, and CSS values for sites like Stripe, Linear, Vercel, Notion, Airbnb, Apple, and more.

**Trigger:** "make it look like Stripe/Linear/Vercel", "style after [known brand]", or when the user references a real product's visual identity.

**What it gives you:** For each brand, a detailed markdown file with: color palette (hex + roles), typography rules, spacing/radius/shadow systems, component patterns, and specific CSS property-value pairs. Ready to copy into HTML artifacts.

**Key references and templates:**
- `references/design-systems-catalog.md` — index of all 54 design systems with descriptions
- `templates/design-systems/` — individual brand files (airbnb.md, apple.md, stripe.md, etc.)

**Usage:** Load the relevant brand file, extract the visual vocabulary, apply it to the HTML artifact. Combine with this skill's design process for best results.

---

## Infographic Generation (baoyu-infographic)

21 layouts × 21 styles for generating visual infographics from content. Use when the user wants an infographic, visual summary, or high-density information graphic (信息图, 可视化).

**Trigger:** "create an infographic", "visual summary", "信息图", "可视化", "high-density info graphic"

**What it gives you:** Two-dimension system — layout (information structure) × style (visual aesthetics). Combine any layout with any style. Includes content analysis framework, structured-content templates, and prompt assembly for image generation.

**Key layouts:** bento-grid, linear-progression, binary-comparison, hub-spoke, iceberg, funnel, dashboard, periodic-table, venn-diagram, winding-roadmap, circular-flow, dense-modules, etc.

**Key styles:** craft-handmade, cyberpunk-neon, technical-schematic, corporate-memphis, chalkboard, pixel-art, etc.

**Key references:**
- `references/infographic-guide.md` — full workflow, layout/style galleries, keyword shortcuts
- `references/infographic/analysis-framework.md` — content analysis methodology
- `references/infographic/base-prompt.md` — base prompt template
- `references/infographic/structured-content-template.md` — content format
- `references/infographic/layouts/` — 21 layout definitions
- `references/infographic/styles/` — 21 style definitions

---

## Pretext Creative Demos (pretext)

Creative browser demos using `@chenglou/pretext` — interactive orb-flow patterns, donut orbits, and generative animations in single HTML files.

**Trigger:** "pretext", "creative browser demo", "orb flow", "generative animation demo"

**What it gives you:** Pattern library and templates for pretext-based creative coding. Pretext provides a minimal runtime for declarative particle/orb animations that respond to mouse movement.

**Key references and templates:**
- `references/pretext-guide.md` — full pretext skill guide
- `references/pretext-patterns.md` — pattern catalog
- `templates/pretext/donut-orbit.html` — donut orbit demo template
- `templates/pretext/hello-orb-flow.html` — orb flow demo template

---

## Text Humanization (humanizer)

Identify and remove signs of AI-generated text to make writing sound natural and human. Use when the user asks to "humanize", "de-AI", "de-slop", or "un-ChatGPT" a piece of text, or when reviewing writing for AI tells before publishing. Also apply to your own prose output when writing release notes, PR descriptions, docs, or long-form summaries.

**Trigger:** "humanize this", "de-AI", "de-slop", "un-ChatGPT", "rewrite so it doesn't sound like AI", "make this sound more natural", "AI writing check"

**What it gives you:** 29 AI-writing patterns (content patterns, language/grammar patterns, style patterns, communication patterns, filler/hedging patterns) plus a voice-calibration workflow, personality-and-soul guidance, and a full worked example showing before/draft/audit/final rewrite.

**Key references:**
- `references/humanizer-patterns.md` — complete pattern catalog, voice calibration process, personality guide, and worked example

**Workflow summary:** Load the reference file → identify AI patterns in the text → rewrite each section → voice-calibrate against a sample if provided → do a final anti-AI pass ("What makes the below so obviously AI generated?") → present final version.

**Pitfalls:** Don't just remove AI patterns — inject actual personality and varied rhythm. Soulless clean text is as obvious as slop. See the PERSONALITY AND SOUL section in the reference.

---

## Variation Rules

When exploring, default to at least three options:

1. **Conservative** — closest to existing patterns / lowest risk
2. **Strong-fit** — best interpretation of the brief
3. **Divergent** — more novel, useful for discovering taste boundaries

Variations can explore:

- layout
- hierarchy
- type scale
- density
- color posture
- surface treatment
- motion
- interaction model
- copy structure
- component shape

Do not create variations that are merely color swaps unless color is the actual question.

When the user picks a direction, consolidate. Do not leave the project as a pile of options forever.

## Sketch Mode (Quick Variant Exploration)

When the user wants to **see a design direction before committing** — exploring a UI/UX idea as disposable HTML mockups. The point is to generate 2-3 interactive variants so the user can compare visual directions side-by-side, not to produce shippable code.

Load this section when the user says things like "sketch this screen", "show me what X could look like", "compare layout A vs B", "give me 2-3 takes on this UI", "let me see some variants", "mockup this before I build".

### Sketch workflow

```
intake  →  variants  →  head-to-head  →  pick winner (or iterate)
```

**1. Intake** — get three things (one question at a time):

1. **Feel.** "What should this feel like? Adjectives, emotions, a vibe."
2. **References.** "What apps, sites, or products capture the feel you're imagining?"
3. **Core action.** "What's the single most important thing a user does on this screen?"

**2. Variants (2-3, never 1, rarely 4+)** — each variant takes a different design stance, not different pixel values. Good variant axes: density (compact/airy), emphasis (content-first/action-first), aesthetic (editorial/utilitarian/playful), layout (single-column/sidebar/split-pane), grounding (card-based/bare-content/document-style).

Variant naming: describe the stance, not the number.

```
sketches/
├── 001-calm-editorial/index.html + README.md
├── 001-utilitarian-dense/index.html + README.md
└── 001-playful-split/index.html + README.md
```

**3. Make them real HTML** — single self-contained HTML file per variant:
- Inline `<style>`, system fonts or one Google Font, Tailwind CDN OK
- Realistic fake content — actual sentences, not "Lorem ipsum"
- **Interactive**: links clickable, hovers real, at least one state transition
- Verify visually with browser tools before showing user

**4. Variant README** — design stance, key choices, trade-offs, best-for use case.

**5. Head-to-head** — comparison table with opinionated take. Let user pick a winner or combine.

### Theming for sketches

If the project has a visual identity, put shared tokens in `sketches/themes/tokens.css` and `@import`. Keep tokens minimal: three colors and one font is usually enough.

### Interactivity bar

A sketch is interactive enough when the user can: (1) click a primary action and something visible happens, (2) see one meaningful state transition, (3) hover recognizable affordances.

### Frontier mode (picking what to sketch next)

If sketches already exist: check consistency gaps between winning variants, unsketched screens, state coverage (empty/loading/error), responsive gaps, interaction patterns not yet explored.

### GSD integration

If `gsd-sketch` shows up as a sibling skill (installed via `npx get-shit-done-cc --hermes`), prefer it for the full workflow: persistent `.planning/sketches/` with MANIFEST, frontier mode analysis, consistency audits. This section is the lightweight standalone version.

## Tweakable Designs in CLI/API Mode

The hosted Claude Design edit-mode toolbar does not exist here.

Still preserve the idea: when useful, add in-page controls called `Tweaks`.

A good `Tweaks` panel can control:

- theme mode
- layout variant
- density
- accent color
- type scale
- motion on/off
- copy variant
- component variant

Keep it small and unobtrusive. The design should look final when tweaks are hidden.

Persist tweak values with localStorage when helpful.

## Content Discipline

Do not add filler content.

Every element must earn its place.

Avoid:

- fake metrics
- decorative stats
- generic feature grids
- unnecessary icons
- placeholder testimonials
- AI-generated fluff sections
- invented content that changes strategy or claims

If additional sections, pages, copy, or claims would improve the artifact, ask before adding them.

When copy is necessary but not final, mark it as draft or placeholder.

## Anti-Slop Rules

Avoid common AI design sludge:

- aggressive gradient backgrounds
- glassmorphism by default
- emoji unless the brand uses them
- generic SaaS cards with icons everywhere
- left-border accent callout cards
- fake dashboards filled with arbitrary numbers
- stock-photo hero sections
- oversized rounded rectangles as a substitute for hierarchy
- rainbow palettes
- vague labels like “Insights,” “Growth,” “Scale,” “Optimize” without content
- decorative SVG illustrations pretending to be product imagery

Minimal is not automatically good. Dense is not automatically cluttered. Choose intentionally.

## Typography

Use the existing type system if one exists.

If not, choose type deliberately based on the artifact:

- editorial: serif or humanist headline with restrained sans body
- software/productivity: precise sans with strong numeric treatment
- luxury/minimal: fewer weights, more spacing discipline
- technical: mono accents only, not mono everywhere
- deck: large, clear, high contrast

Avoid overused defaults when a stronger choice is appropriate.

If using web fonts, keep the number of families and weights low.

Use type as hierarchy before adding boxes, icons, or color.

## Color

Use brand/design-system colors first.

If no palette exists:

- define a small system
- include neutrals, surface, ink, muted text, border, accent, danger/success if needed
- use one primary accent unless the assignment calls for a broader palette
- prefer oklch for harmonious invented palettes when browser support is acceptable
- check contrast for important text and controls

Do not invent lots of colors from scratch.

## Layout and Composition

Design with rhythm:

- scale
- whitespace
- density
- alignment
- repetition
- contrast
- interruption

Avoid making every section the same card grid.

For product UIs, prioritize speed of comprehension over decoration.

For marketing surfaces, make one idea land per section.

For dashboards, avoid “data slop.” Only show data that helps the user decide or act.

## Motion

Use motion as discipline, not theater.

Good motion:

- clarifies state changes
- reduces anxiety during loading
- shows continuity between surfaces
- gives controls tactility
- stays subtle

Bad motion:

- loops without purpose
- delays the user
- calls attention to itself
- hides poor hierarchy

Respect `prefers-reduced-motion` for non-trivial animation.

## Images and Icons

Use real supplied imagery when available.

If an asset is missing:

- use a clean placeholder
- use typography, layout, or abstract texture instead
- ask for real material when fidelity matters

Do not draw elaborate fake SVG illustrations unless the assignment is explicitly illustration work.

Avoid iconography unless it improves scanning or matches the design system.

## Source-Code Fidelity

When recreating or extending a UI from a repo:

1. inspect the repo tree
2. identify the actual UI source files
3. read theme/token/global style/component files
4. lift exact values where appropriate
5. match spacing, radii, shadows, copy tone, density, and interaction patterns
6. only then design or modify

Do not build from memory when source files are available.

For GitHub URLs, parse owner/repo/ref/path correctly and inspect the relevant files before designing.

## Reading Documents and Assets

Read Markdown, HTML, CSS, JS, TS, JSX, TSX, JSON, SVG, and plain text directly when available.

For DOCX/PPTX/PDF, use available local extraction tools if present. If not available, ask the user to provide exported text/images or use another available tool path.

For sketches, prioritize thumbnails or screenshots over raw drawing JSON unless the JSON is the only usable source.

## Copyright and Reference Models

Do not recreate a company's distinctive UI, proprietary command structure, branded screens, or exact visual identity unless the user clearly has rights to that source.

It is acceptable to extract general design principles:

- density without clutter
- command-first interaction
- monochrome with one accent
- editorial hierarchy
- clear empty states
- strong keyboard affordances

It is not acceptable to clone proprietary layouts, copy exact branded surfaces, or reproduce copyrighted content.

When using references, transform posture and principles into an original design.

## Verification

Before final response, verify as much as the environment allows.

Minimum:

- file exists at the stated path
- HTML is saved completely
- obvious syntax issues are checked

Better:

- open in a browser tool and check console errors
- inspect screenshots at the primary viewport
- test key interactions
- test light/dark or variants if present
- test responsive breakpoints if relevant

If verification is limited by environment, say exactly what was and was not verified.

Never say “done” if the file was not actually written.

## Final Response Format

Keep final responses short.

Include:

- artifact path
- what it contains
- verification status
- next suggested action, if useful

Example:

```text
Created: /path/to/Prototype.html
It includes 3 layout variants, a Tweaks panel for density/theme, and responsive behavior.
Verified: file exists and opened cleanly in browser, no console errors.
Next: pick the strongest direction and I’ll tighten copy + motion.
```

## Portable Opening Prompt Pattern

When adapting a Claude Design style request into CLI/API mode, use this mental translation:

```text
You are running in CLI/API mode, not hosted Claude Design. Ignore references to hosted-only tools or preview panes. Produce complete local design artifacts, usually self-contained HTML with embedded CSS/JS, and verify with available local tools before returning. Preserve the design process: gather context, define the system, produce options, avoid filler, and meet a high visual bar.
```

## References and Templates

| Path | Contents |
|------|----------|
| `references/design-md-spec.md` | Full DESIGN.md token spec format, lint rules, workflow, pitfalls |
| `references/design-systems-catalog.md` | Index of all 54 known-brand design system files |
| `references/pretext-guide.md` | Pretext creative demo skill guide |
| `references/pretext-patterns.md` | Pretext pattern catalog |
| `references/infographic-guide.md` | Full infographic generation workflow, layout/style galleries |
| `references/infographic/` | Infographic analysis framework, prompt templates, layout & style definitions |
| `references/humanizer-patterns.md` | 29 AI-writing patterns, voice calibration, personality guide, worked example |
| `templates/design-md-starter.md` | Starter DESIGN.md template |
| `templates/design-systems/` | 54 individual brand design system files (airbnb.md, stripe.md, etc.) |
| `templates/pretext/` | Pretext HTML templates (donut-orbit.html, hello-orb-flow.html) |

## Pitfalls

- Do not paste hosted tool schemas into a skill. They cause fake tool calls.
- Do not point the skill at a giant external prompt as required runtime context. That creates drift.
- Do not strip the design doctrine while removing tool plumbing.
- Do not over-ask when the user already gave enough direction.
- Do not under-ask for high-fidelity work with no brand context.
- Do not produce generic SaaS layouts and call them designed.
- Do not claim browser verification unless it actually happened.
