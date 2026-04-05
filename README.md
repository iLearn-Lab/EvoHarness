<div align="center">
  <img src="./.github/assets/evoharness-banner.svg" alt="EvoHarness" width="100%">
</div>

<div align="center">
  <img src="./.github/assets/evoharness-cli-demo.svg" alt="EvoHarness CLI demo" width="94%">
</div>

<p align="center">
  <strong>English</strong> | <a href="./README.zh-CN.md">ZH-CN</a>
</p>

<p align="center">
  Terminal-native agent harness for coding workflows and controlled self-evolution research <code>(^_^)/</code>
</p>

<p align="center">
  markdown-first | plugin-native | MCP-ready | session-aware | self-evolving
</p>

<p align="center">
  <a href="#quick-start"><img src="https://img.shields.io/badge/Quick_Start-Launch_Now-2563EB?style=for-the-badge" alt="Quick Start"></a>
  <a href="#core-surfaces"><img src="https://img.shields.io/badge/Surface-Commands_+_Skills_+_Agents-0EA5E9?style=for-the-badge" alt="Surface"></a>
  <a href="#controlled-self-evolution"><img src="https://img.shields.io/badge/Self--Evolution-Controlled-7C3AED?style=for-the-badge" alt="Self Evolution"></a>
  <a href="#plugin-and-mcp-ecosystem"><img src="https://img.shields.io/badge/Plugins_+_MCP-Bundled-F59E0B?style=for-the-badge" alt="Plugins and MCP"></a>
  <a href="./docs/architecture.md"><img src="https://img.shields.io/badge/Docs-Architecture-334155?style=for-the-badge" alt="Docs"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/runtime-terminal--native-0F172A?style=flat-square" alt="Runtime">
  <img src="https://img.shields.io/badge/license-Apache--2.0-FACC15?style=flat-square" alt="License">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/tools-26-14B8A6?style=flat-square" alt="Tools">
  <img src="https://img.shields.io/badge/commands-32-0EA5E9?style=flat-square" alt="Commands">
  <img src="https://img.shields.io/badge/skills-34-06B6D4?style=flat-square" alt="Skills">
  <img src="https://img.shields.io/badge/agents-32-3B82F6?style=flat-square" alt="Agents">
  <img src="https://img.shields.io/badge/plugins-7-F59E0B?style=flat-square" alt="Plugins">
  <img src="https://img.shields.io/badge/mcp_servers-10-8B5CF6?style=flat-square" alt="MCP Servers">
</p>

> **EvoHarness** makes the harness itself explicit: tools, commands, skills, agents, plugins, MCP, memory, approvals, sessions, and evolution operators stay visible, editable, and inspectable.
>
> This GitHub release is intentionally trimmed for publication. It keeps the runtime, frontend, plugins, default ecosystem, and docs, while removing tests, examples, caches, and local noise `(._.)`

---

## Why EvoHarness

<table>
  <tr>
    <td width="33%" valign="top">
      <strong>Terminal Runtime</strong><br><br>
      - interactive CLI / TUI<br>
      - slash-command workflow control<br>
      - tool execution, streaming, and approvals
    </td>
    <td width="33%" valign="top">
      <strong>Markdown Workflow Surface</strong><br><br>
      - 32 commands<br>
      - 34 skills<br>
      - 32 agents<br>
      - repo-native workflow packaging
    </td>
    <td width="33%" valign="top">
      <strong>Plugin + MCP</strong><br><br>
      - 7 bundled plugins<br>
      - 10 MCP servers<br>
      - tools / resources / prompts<br>
      - marketplace-ready layout
    </td>
  </tr>
  <tr>
    <td width="33%" valign="top">
      <strong>Governance</strong><br><br>
      - approvals and permission modes<br>
      - hooks and policy surfaces<br>
      - session archives and task control
    </td>
    <td width="33%" valign="top">
      <strong>Self-Evolution</strong><br><br>
      - trace-to-plan bridge<br>
      - revise command / skill / memory<br>
      - candidate, promote, rollback<br>
      - ecosystem growth operators
    </td>
    <td width="33%" valign="top">
      <strong>Public Release Shape</strong><br><br>
      - source, frontend, plugins, docs<br>
      - public CLAUDE surface<br>
      - bundled marketplace and MCP registry<br>
      - clean GitHub-ready repository layout
    </td>
  </tr>
</table>

---

## Quick Start

### Requirements

- Python 3.11+
- Node.js 18+ if you want the React/Ink terminal frontend

### Fastest Source Launch

```bash
git clone https://github.com/HITSZ-DS/EvoHarness.git
cd EvoHarness
python -m evo_harness
```

`python -m evo_harness` is the simplest entrypoint from a source checkout `(^_^)/`

If `npm` is available, the frontend dependencies are installed automatically on the first TUI launch.

### Optional Editable Install

If you want the shorter CLI alias:

```bash
python -m pip install -e .
evoh
```

### Useful First Commands

```bash
evoh doctor --workspace .
evoh tools-list --workspace .
evoh commands-list --workspace .
evoh agents-list --workspace .
evoh mcp-list --workspace . --kind all
```

### Inside the Session

```text
/help
/permissions
/resume
/plugins
/plugins marketplaces
/docs-refresh onboarding flow
/workflow-blueprint provider debugging
```

---

## Core Surfaces

Current release surface:

- **26 builtin tools** for files, search, shell, JSON, tasks, registry inspection, MCP, and subagents
- **32 markdown commands** for repeatable terminal workflows
- **34 skills** for on-demand workflow guidance
- **32 agents** for bounded delegation and structured inspection
- **7 bundled plugins** for web research, workspace ops, delivery, docs, sessions, safety, and ecosystem growth
- **10 MCP servers** exposing **29 tools**, **27 resources**, and **10 prompts**

The repo ships the harness as a **real workspace**, not only as a library.  
That means `.claude/`, `plugins/`, and `.evo-harness/mcp.json` are part of the product surface `(._.)`

---

## Controlled Self-Evolution

EvoHarness treats self-evolution as a **controlled systems problem** rather than an aesthetic slogan.

The main loop is:

1. archive real sessions and runtime traces
2. analyze where the harness stalled, over-explored, or under-supported the task
3. propose an operator such as:
   `stop`, `distill_memory`, `revise_command`, `revise_skill`, or `grow_ecosystem`
4. produce candidate changes
5. validate before promotion
6. promote, keep as candidate, or rollback

```mermaid
flowchart LR
    U[User Task] --> R[Harness Runtime]
    R --> S[Archived Sessions / Traces]
    S --> A[Analysis + Evolution Bridge]
    A --> O[Operator Proposal]
    O --> C[Candidate Patch]
    C --> V[Validation Gate]
    V -->|promote| P[Promoted Workspace]
    V -->|rollback| B[Rollback Path]
    V -->|hold| K[Candidate Only]
```

Research-wise, the emphasis is on:

- observable failure modes
- bounded operator choices
- workspace-native evolution artifacts
- promotion / rollback discipline

---

## Repository Layout

```text
EvoHarness/
  src/evo_harness/         # core runtime, CLI, harness modules, evolution bridge
  frontend/terminal/       # React + Ink terminal frontend
  plugins/                 # bundled plugin ecosystem
  .claude/                 # default commands, skills, and agents
  .evo-harness/            # default MCP and marketplace registry
  docs/                    # architecture and project positioning docs
  scripts/                 # live / chat / self-evolution workbenches
  CLAUDE.md                # public project instruction surface
```

Trimmed from this GitHub-ready release:

- `tests/`
- `examples/`
- `node_modules/`
- runtime logs, caches, and generated local state

---

## Plugin and MCP Ecosystem

Bundled plugins:

- `safe-inspector`
- `evolution-studio`
- `web-research`
- `workspace-ops`
- `delivery-lab`
- `docs-foundry`
- `session-lab`

Bundled local MCP servers:

- `workspace-docs`
- `workspace-intel`
- `quality-gate`
- `docs-gap`
- `session-lab`
- plus plugin-scoped MCP surfaces for the corresponding plugins

This gives the repo a practical default ecosystem for:

- docs search and repair
- workspace surface inspection
- release-readiness review
- session and approval forensics
- public-web research
- plugin and workflow design

---

## Visual Assets `(._.)`

The repository already includes one local banner for GitHub display.

For the next visual pass, see [docs/ASSET_PLAN.md](./docs/ASSET_PLAN.md).

That file lists:

- which screenshots are best provided by you
- which visuals are better generated or illustrated
- ready-to-use prompts for AI-generated assets

---

## Citation

If you want to cite EvoHarness as software:

```bibtex
@software{evoharness2026,
  title  = {EvoHarness: A Terminal-Native Agent Harness with Controlled Self-Evolution},
  author = {EvoHarness Contributors},
  year   = {2026},
  url    = {https://github.com/HITSZ-DS/EvoHarness}
}
```

A machine-readable citation file is also provided in [CITATION.cff](./CITATION.cff).

---

## License

Apache-2.0. See [LICENSE](./LICENSE).
