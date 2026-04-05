<table align="center">
  <tr>
    <td align="center" valign="middle" width="180">
      <img src="./.github/assets/evoharness-mark.png" alt="EvoHarness mark" width="132">
    </td>
    <td align="left" valign="middle">
      <img src="./.github/assets/evoharness-wordmark.svg" alt="EvoHarness wordmark" width="760">
    </td>
  </tr>
</table>

<p align="center">
  <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=600&pause=1300&color=7DD3FC&center=true&vCenter=true&width=980&lines=EvoHarness+%2F%2F+Terminal-Native+Agent+Harness;Controlled+Self-Evolution+%2F%2F+Plugins+%2F%2F+MCP;Coding+workflows+with+visible+harness+surfaces" alt="EvoHarness typing intro" />
</p>

<p align="center">
  <strong>English</strong> | <a href="./README.zh-CN.md">ZH-CN</a>
</p>

<p align="center">
  <strong>EvoHarness delivers terminal-native agent infrastructure:</strong>
  tools, commands, skills, agents, plugins, MCP, memory, approvals, and controlled self-evolution.
</p>

<p align="center">
  <strong>Build with the project:</strong> shape an open, visible, and research-grade harness for coding workflows.
</p>

<p align="center">
  <a href="#quick-start"><img src="https://img.shields.io/badge/QUICK_START-5_MIN-0EA5E9?style=for-the-badge" alt="Quick Start"></a>
  <a href="#harness-architecture"><img src="https://img.shields.io/badge/HARNESS-ARCHITECTURE-F472B6?style=for-the-badge" alt="Harness Architecture"></a>
  <a href="#controlled-self-evolution"><img src="https://img.shields.io/badge/SELF_EVOLUTION-CONTROLLED-84CC16?style=for-the-badge" alt="Controlled Self Evolution"></a>
  <a href="#plugin-mcp-ecosystem"><img src="https://img.shields.io/badge/PLUGINS-7-F59E0B?style=for-the-badge" alt="Plugins"></a>
  <a href="#documentation"><img src="https://img.shields.io/badge/DOCS-5_GUIDES-334155?style=for-the-badge" alt="Docs"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/LICENSE-Apache_2.0-FACC15?style=for-the-badge" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-%3E%3D3.11-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/React%2BInk-TUI-61DAFB?logo=react&logoColor=white" alt="React Ink TUI">
  <img src="https://img.shields.io/badge/tools-26-14B8A6" alt="26 tools">
  <img src="https://img.shields.io/badge/commands-32-0EA5E9" alt="32 commands">
  <img src="https://img.shields.io/badge/skills-34-06B6D4" alt="34 skills">
  <img src="https://img.shields.io/badge/agents-32-3B82F6" alt="32 agents">
  <img src="https://img.shields.io/badge/plugins-7-F59E0B" alt="7 plugins">
  <img src="https://img.shields.io/badge/MCP_servers-10-8B5CF6" alt="10 MCP servers">
  <img src="https://img.shields.io/badge/MCP_tools-29-7C3AED" alt="29 MCP tools">
</p>

<a id="controlled-self-evolution"></a>
## 🧠✨ Controlled Self-Evolution (-_-)

<div align="center">
  <img src="./.github/assets/evoharness-promotion-gate.png" alt="EvoHarness promotion gate" width="100%">
</div>

<p align="center">
  <strong>🌌 Evidence, operators, candidate patches, and promotion paths 🩵</strong>
</p>

EvoHarness treats self-evolution as **control over the harness surface**, not as unconstrained agent autonomy.

The real question is not "can the model rewrite itself once," but:

- 🧾 **when to evolve**: use real sessions, traces, failures, approvals, and workspace state as evidence
- 🎛️ **which operator to choose**: `revise_command`, `revise_skill`, `distill_memory`, `grow_ecosystem`, or `stop`
- 🛑 **when not to evolve**: low-value changes should be filtered before mutation
- ✅ **how changes enter the runtime**: candidate patches must pass validation, then get promoted, held, or rolled back

So the loop can be read in one line:

**evidence -> operator choice -> candidate patch -> validation -> promote / hold / rollback**

In short, EvoHarness studies self-evolution as a **long-horizon operator-control problem** over commands, skills, agents, plugins, MCP, memory, and policy surfaces.

<p align="center">
  <img src="./.github/assets/evoharness-mascot-evolution-lineup.png" alt="EvoHarness mascot evolution lineup" width="96%">
</p>

<p align="center">
  <strong>🐴 Three-stage mascot evolution: saddle -> harness -> elegant evolution ✨🩵</strong>
</p>

---

<a id="harness-architecture"></a>
## 🧩 Harness Architecture \(^_^)/ 

<div align="center">
  <img src="./.github/assets/evoharness-architecture.svg" alt="EvoHarness architecture overview" width="100%">
</div>

EvoHarness makes the harness observable, countable, and evolvable.

At the system surface, it exposes:

- 🛠️ **26 tools** for files, shell, search, tasks, registry, MCP, and subagents
- 🧾 **32 commands** as workflow entry points
- 🧠 **34 skills** as on-demand procedural guidance
- 🤖 **32 agents** for bounded delegation
- 🔌 **7 plugins** for workspace-native ecosystem growth
- 🛰️ **10 MCP servers / 29 MCP tools** for external tools, resources, and prompts

Architecturally, the runtime ties together:

- terminal-native control
- markdown-native workflow packaging
- plugin-native extensibility
- MCP-native ecosystem access
- memory, approvals, analytics, and evolution planning in the same runtime

In short: the harness is not background glue, it is the primary engineered surface `(^_^)`

---

<a id="quick-start"></a>
## 🚀 Quick Start \(^o^)/

### Requirements

- Python 3.11+
- Node.js 18+ if you want the React/Ink terminal frontend

### Fastest Source Launch

```bash
git clone https://github.com/HITSZ-DS/EvoHarness.git
cd EvoHarness
python -m evo_harness
```

If `npm` is available, frontend dependencies are installed automatically on the first TUI launch `(^_^)/`

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

<a id="plugin-mcp-ecosystem"></a>
## 🕸️ Plugin and MCP Ecosystem (╭☞•́⍛•̀)╭☞

Bundled plugins:

- `safe-inspector`
- `evolution-studio`
- `web-research`
- `workspace-ops`
- `delivery-lab`
- `docs-foundry`
- `session-lab`

Bundled MCP surfaces cover:

- docs search and repair
- workspace surface inspection
- release-readiness review
- session and approval forensics
- public-web research
- plugin and workflow design

<div align="center">
  <img src="./.github/assets/evoharness-ecosystem.svg" alt="EvoHarness ecosystem overview" width="100%">
</div>

Current runtime surface:

- **26 builtin tools**
- **32 commands**
- **34 skills**
- **32 agents**
- **7 plugins**
- **10 MCP servers**
- **29 MCP tools / 27 MCP resources / 10 MCP prompts**

---

<a id="documentation"></a>
## 📚 Documentation (•‿•)

- [Architecture](./docs/architecture.md)
- [Feature Matrix (zh-CN)](./docs/feature-matrix.zh-CN.md)
- [Project Positioning (zh-CN)](./docs/project-positioning.zh-CN.md)
- [Roadmap (zh-CN)](./docs/roadmap.zh-CN.md)
- [OpenHarness Reference](./docs/openharness-reference.md)

---

## 📝 Citation (._.)

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

## 📄 License

Apache-2.0. See [LICENSE](./LICENSE).
