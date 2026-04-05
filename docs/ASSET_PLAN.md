# Asset Plan

This file is the image-generation playbook for EvoHarness.

The priorities are:

1. make the project look like a serious systems-and-agents research repo
2. emphasize **harness** and **controlled self-evolution**
3. avoid generic AI art that says nothing about the project

The README hero now uses:

- `./.github/assets/evoharness-mark.svg` for the **left-side project mark**
  or `./.github/assets/evoharness-mark.png` if you replace it with a raster image

If you find a better left-side image, the easiest path is simply:

1. keep the same filename
2. replace that one asset
3. push again

---

## Recommended Asset Set

If you want the README to feel full and polished, the best set is:

1. **Hero mark + title block**
2. **Real CLI screenshot**
3. **Harness feature infographic**
4. **Self-evolution pipeline figure**
5. **Architecture overview figure**
6. **Ecosystem overview figure**
7. **Benchmark or result figure**

The repository already includes SVG placeholders for items 1, 3, 4, 5, and 6.

The two highest-value real images you can still provide are:

- a real terminal screenshot
- a real benchmark / experimental result figure

---

## Ratio Guide

Based on the generator sizes you showed, these are the best ratios:

| Asset | Best ratio | Why |
|------|------------|-----|
| Hero mark | `1:1` | best for the left-side logo / mascot |
| Hero background strip | `21:9` | useful if you later return to a full-width banner |
| CLI screenshot | `16:9` | reads naturally under the hero |
| Harness features infographic | `16:9` or `4:3` | wide enough for multiple cards |
| Self-evolution pipeline | `16:9` | good for left-to-right process flow |
| Architecture overview | `16:9` | ideal for system diagrams |
| Ecosystem overview | `16:9` | works well for grouped surfaces |
| Benchmark figure | `4:3` | best for plots / ablations |
| Mascot / logo | `1:1` | easiest to reuse everywhere |
| Poster-style academic visual | `3:4` or `2:3` | useful for social posts or docs |
| Mobile promo image | `9:16` | only if you later add mobile surfaces |

If you only want one universal choice for README visuals, choose **`16:9`**.  
If you are generating the top hero, choose **`21:9`**.

---

## Best Images To Provide Manually

These are more valuable as **real screenshots or real figures** than as generated art.

### 1. Terminal Landing Screenshot

Best ratio: `16:9`

What to show:

- the welcome screen
- command / skill / agent / plugin / MCP counts
- dark terminal UI

Best target size:

- `1600x900`
- `1920x1080`

### 2. Real Session Screenshot

Best ratio: `16:9`

What to show:

- one real session
- command activation
- tool execution
- status bar or transcript

### 3. Self-Evolution Figure

Best ratio: `16:9` or `4:3`

Best source:

- a real paper figure
- a real lab diagram
- a cleaned-up benchmark workflow chart

### 4. Benchmark / Result Figure

Best ratio: `4:3`

What to show:

- benchmark ranking
- ablation
- controlled self-evolution comparison
- plugin / MCP / workflow gains

This one adds the most academic credibility.

---

## AI Generation Prompts

Use these when you do not already have official visuals.

### A. Hero Mark

Best ratio: `1:1`

```text
A clean futuristic AI harness emblem for a project called EvoHarness, blue-cyan palette, systems research feel, polished vector mark, geometric node motifs, professional open-source branding, transparent background, not cartoonish, not childish, suitable for a GitHub project hero
```

### B. Hero Background Strip

Best ratio: `21:9`

```text
A premium GitHub README hero banner for a project called EvoHarness, terminal-native agent harness, controlled self-evolution, blue and cyan scientific infrastructure aesthetic, subtle network geometry, elegant engineering design, serious open-source systems research tone, large clean title area, minimal but powerful, no extra words, no watermark
```

### C. Realistic CLI Promo

Best ratio: `16:9`

```text
A realistic terminal UI promotional image for an open-source project called EvoHarness, dark coding terminal, futuristic but believable CLI, rich transcript area, command palette, status indicators, cyber blue and cyan accents, clean typography, serious research-engineering style, not cartoonish, no fantasy UI, suitable for GitHub README
```

### D. Harness Features Infographic

Best ratio: `16:9`

```text
A polished technical infographic for an AI systems project called EvoHarness, showing five feature pillars: agent loop, harness toolkit, context and memory, governance, ecosystem, clean academic infographic design, card-based layout, blue cyan violet orange accents, readable and structured, suitable for an open-source README
```

### E. Self-Evolution Pipeline

Best ratio: `16:9`

```text
A serious technical diagram showing controlled self-evolution for an agent harness: archived sessions and traces, analysis, bounded operator proposal, candidate patch generation, validation gate, promotion, hold, rollback, dark systems-research style, elegant academic visualization, blue cyan violet highlights, no decorative clutter
```

### F. Harness Architecture Figure

Best ratio: `16:9`

```text
A clean systems architecture illustration for a project called EvoHarness, showing user interaction, runtime, tools, markdown workflow surfaces, plugins, MCP, memory, approvals, session archive, analytics, and evolution planning, modern academic engineering style, readable, high signal, suitable for a GitHub README
```

### G. Ecosystem Overview Figure

Best ratio: `16:9`

```text
A structured infographic showing the ecosystem of a terminal-native agent harness project: plugins, commands, skills, agents, MCP servers, runtime state, and evolution control, clean white or light research-card layout, strong typography, blue and orange accents, systems and platform engineering aesthetic
```

### H. Mascot / Logo

Best ratio: `1:1`

```text
A clean futuristic AI harness mascot, blue-cyan palette, academic engineering tone, terminal-native feel, subtle circuit motifs, polished open-source branding, transparent background, not chibi, not cartoonish, not childish, professional and memorable
```

### I. Benchmark Figure Background

Best ratio: `4:3`

```text
A serious scientific presentation background for benchmark and ablation charts, designed for a project called EvoHarness, minimal blue-cyan systems research aesthetic, clean grid and subtle technical motifs, high readability, suitable for overlaying plots and tables
```

---

## Suggested Generation Order

If you want to generate only a few images first:

1. `1:1` hero mark
2. `16:9` realistic CLI promo
3. `16:9` self-evolution pipeline
4. `16:9` harness architecture
5. `4:3` benchmark figure background

That order gives the fastest visible improvement to the GitHub homepage.
