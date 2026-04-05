<p align="center">
  <img src="./.github/assets/evoharness-mark.png" alt="EvoHarness mark" width="152">&nbsp;&nbsp;&nbsp;&nbsp;
  <img src="./.github/assets/evoharness-wordmark.svg" alt="EvoHarness wordmark" width="760">
</p>

<p align="center">
  <img src="./.github/assets/evoharness-cli-demo.svg" alt="EvoHarness CLI demo" width="98%">
</p>

<p align="center">
  <strong>English</strong> | <a href="./README.zh-CN.md">ZH-CN</a>
</p>

<p align="center">
  <strong>Terminal-Native Agent Harness</strong>
</p>

<p align="center">
  Coding workflows | plugins | MCP | approvals | controlled self-evolution \(^o^)/
</p>

<p align="center">
  make the harness feel alive, sharp, and research-grade  (^_^)/ 
</p>

<p align="center">
  <a href="#-quick-start"><img src="https://img.shields.io/badge/Quick_Start-python_-m_evo__harness-2563EB?style=for-the-badge" alt="Quick Start"></a>
  <a href="#-key-harness-features"><img src="https://img.shields.io/badge/Harness-Surfaces-0EA5E9?style=for-the-badge" alt="Harness Surfaces"></a>
  <a href="#-controlled-self-evolution"><img src="https://img.shields.io/badge/Self--Evolution-Controlled-7C3AED?style=for-the-badge" alt="Self Evolution"></a>
  <a href="#-harness-architecture"><img src="https://img.shields.io/badge/Architecture-Visible-334155?style=for-the-badge" alt="Architecture"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/tools-26-14B8A6?style=flat-square" alt="Tools">
  <img src="https://img.shields.io/badge/commands-32-0EA5E9?style=flat-square" alt="Commands">
  <img src="https://img.shields.io/badge/skills-34-06B6D4?style=flat-square" alt="Skills">
  <img src="https://img.shields.io/badge/agents-32-3B82F6?style=flat-square" alt="Agents">
  <img src="https://img.shields.io/badge/plugins-7-F59E0B?style=flat-square" alt="Plugins">
  <img src="https://img.shields.io/badge/mcp_servers-10-8B5CF6?style=flat-square" alt="MCP Servers">
</p>

EvoHarness turns the harness from hidden glue into a visible, extensible, and research-grade system surface.

Its core orientation is **harness research**:

- how terminal-native coding agents should expose tools, workflow surfaces, and governance
- how archived runtime evidence can drive **controlled** self-evolution
- how markdown, plugins, and MCP can act as real research and engineering surfaces

---

## ✨ Key Harness Features \(^_^)/ 

<div align="center">
  <img src="./.github/assets/evoharness-features.svg" alt="EvoHarness key harness features" width="100%">
</div>

EvoHarness combines five high-leverage surfaces:

- **Agent Loop** for iterative tool-use and session control
- **Harness Toolkit** for files, shell, search, task, registry, MCP, and subagent operations
- **Context & Memory** for prompt assembly, instructions, archive, and resume
- **Governance** for approvals, permissions, hooks, and promotion discipline
- **Ecosystem** for plugins, MCP, commands, skills, and agents as first-class runtime artifacts

---

## 🧠 Controlled Self-Evolution (-_-)

<div align="center">
  <img src="./.github/assets/evoharness-self-evolution.svg" alt="Controlled self-evolution pipeline" width="100%">
</div>

EvoHarness treats self-evolution as a **bounded runtime pipeline** rather than an unconstrained autonomous loop.

The main process is:

1. archive real sessions, tool histories, and runtime traces
2. analyze failure modes, ecosystem gaps, and repeated coordination pressure
3. choose a small operator family such as `stop`, `distill_memory`, `revise_command`, `revise_skill`, or `grow_ecosystem`
4. produce candidate patches against the real workspace
5. validate before promotion
6. promote, hold as candidate, or rollback

This design emphasizes:

- observable failure modes
- explicit operator choice
- candidate-first evolution
- promotion and rollback discipline
- workspace-native artifacts instead of hidden internal state

---

## 🧩 Harness Architecture (^_^)

<div align="center">
  <img src="./.github/assets/evoharness-architecture.svg" alt="EvoHarness architecture overview" width="100%">
</div>

The runtime ties together:

- terminal interaction and slash-command control
- tool execution, approvals, tasks, and session state
- visible workflow surfaces in `.claude/`
- plugin and MCP ecosystems
- memory, analytics, and evolution planning

The architectural stance is simple: the harness is not background glue, it is the primary system under study.

---

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
