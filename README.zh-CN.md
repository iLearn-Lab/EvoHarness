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
  <a href="./README.md">English</a> | <strong>????</strong>
</p>

## ?? ?????

<div align="center">
  <img src="./.github/assets/evoharness-self-evolution.svg" alt="Controlled self-evolution pipeline" width="100%">
</div>

EvoHarness ??????????? **bounded runtime pipeline**????????????

?????

1. archive ?? sessions?tool histories ? runtime traces
2. analyze failure modes?ecosystem gaps ? coordination pressure
3. ???? operator family ??????? `stop`?`distill_memory`?`revise_command`?`revise_skill`?`grow_ecosystem`
4. ???? workspace ?? candidate patches
5. validate before promotion
6. promote?hold ? rollback

????

- failure modes ???
- operator choice ???
- candidate-first evolution
- promotion / rollback discipline
- workspace-native artifacts??????????

---

## ?? Harness ??

<div align="center">
  <img src="./.github/assets/evoharness-architecture.svg" alt="EvoHarness architecture overview" width="100%">
</div>

?????????????

- terminal interaction ? slash-command control
- tool execution?approvals?tasks?session state
- `.claude/` ???? workflow surfaces
- plugin ? MCP ecosystem
- memory?analytics ? evolution planning

?????????????**harness ????????????????**

---

## ?? ????

### ????

- Python 3.11+
- Node.js 18+?????? React/Ink terminal frontend?

### ??????

```bash
git clone https://github.com/HITSZ-DS/EvoHarness.git
cd EvoHarness
python -m evo_harness
```

????? `npm`??? TUI ???????????? `(^_^)/`

### ????????

??????????????

```bash
python -m pip install -e .
evoh
```

### ???????

```bash
evoh doctor --workspace .
evoh tools-list --workspace .
evoh commands-list --workspace .
evoh agents-list --workspace .
evoh mcp-list --workspace . --kind all
```

### ???????

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

## ??? Plugin ? MCP ??

Bundled plugins:

- `safe-inspector`
- `evolution-studio`
- `web-research`
- `workspace-ops`
- `delivery-lab`
- `docs-foundry`
- `session-lab`

Bundled local MCP surfaces ???

- docs search ? repair
- workspace surface inspection
- release-readiness review
- session ? approval forensics
- public-web research
- plugin ? workflow design

?? runtime surface?

- **26 builtin tools**
- **32 commands**
- **34 skills**
- **32 agents**
- **7 plugins**
- **10 MCP servers**
- **29 MCP tools / 27 MCP resources / 10 MCP prompts**

---

## ?? ??

- [Architecture](./docs/architecture.md)
- [Feature Matrix (zh-CN)](./docs/feature-matrix.zh-CN.md)
- [Project Positioning (zh-CN)](./docs/project-positioning.zh-CN.md)
- [Roadmap (zh-CN)](./docs/roadmap.zh-CN.md)
- [OpenHarness Reference](./docs/openharness-reference.md)

---

## ?? ??

?????? EvoHarness ?????????

```bibtex
@software{evoharness2026,
  title  = {EvoHarness: A Terminal-Native Agent Harness with Controlled Self-Evolution},
  author = {EvoHarness Contributors},
  year   = {2026},
  url    = {https://github.com/HITSZ-DS/EvoHarness}
}
```

?????? [CITATION.cff](./CITATION.cff)?

---

## ?? License

Apache-2.0?? [LICENSE](./LICENSE)?
