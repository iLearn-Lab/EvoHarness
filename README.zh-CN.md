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
  <a href="./README.md">English</a> | <strong>简体中文</strong>
</p>

## 🧠 可控自进化

<div align="center">
  <img src="./.github/assets/evoharness-self-evolution.svg" alt="Controlled self-evolution pipeline" width="100%">
</div>

EvoHarness 将“自进化”定义为一个**受约束的系统闭环**，作用对象不是模型本身，而是 harness 的可见工程表面。

这个方向成立的前提有三点：

1. **证据真实**：进化依据来自真实 sessions、tool histories、approvals、failures 与 workspace state  
2. **动作有界**：变化通过显式 operator family 提出，例如 `distill_memory`、`revise_command`、`revise_skill`、`grow_ecosystem`  
3. **提升受治理**：candidate patch 必须经过 validation、promotion policy 与 rollback discipline  

在 EvoHarness 中，进化目标主要包括：

- commands 与 skills
- agents 与 plugin bundles
- MCP registries 与 workflow ecosystems
- persistent memory 与 instruction layers
- promotion 与 safety policy surfaces

运行闭环是：

1. archive sessions、traces、tool histories 与 failure evidence  
2. analyze harness 在哪里欠支持任务、或过度探索搜索空间  
3. choose a bounded operator family  
4. materialize candidate patches against the real workspace  
5. validate before promotion  
6. promote、hold 或 rollback  

这套设计强调：

- 证据驱动，而不是凭空自改
- operator 语义显式，而不是自由变异
- candidate-first progression，而不是直接改动 active surface
- promotion / rollback discipline，而不是不可逆漂移
- workspace-native artifacts，而不是隐藏内部状态

从研究角度看，EvoHarness 的价值在于把这三件事都暴露出来：

- 改进压力来自哪里
- 允许改变什么
- 这些变化如何进入 active runtime

---

## 🧩 Harness 架构

<div align="center">
  <img src="./.github/assets/evoharness-architecture.svg" alt="EvoHarness architecture overview" width="100%">
</div>

运行时把这些部分连接起来：

- terminal interaction 与 slash-command control
- tool execution、approvals、tasks、session state
- `.claude/` 中的可见 workflow surfaces
- plugin 与 MCP ecosystem
- memory、analytics 与 evolution planning

这个项目的架构立场很直接：**harness 不是背景胶水，而是主要研究对象。**

---

## 🚀 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+（如果需要 React/Ink terminal frontend）

### 最快启动方式

```bash
git clone https://github.com/HITSZ-DS/EvoHarness.git
cd EvoHarness
python -m evo_harness
```

如果本机存在 `npm`，首次 TUI 启动时会自动安装前端依赖 `(^_^)/`

### 可选命令别名

如果你想直接使用更短的命令：

```bash
python -m pip install -e .
evoh
```

### 建议先跑的命令

```bash
evoh doctor --workspace .
evoh tools-list --workspace .
evoh commands-list --workspace .
evoh agents-list --workspace .
evoh mcp-list --workspace . --kind all
```

### 会话内常用入口

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

## 🕸️ Plugin 与 MCP 生态

Bundled plugins:

- `safe-inspector`
- `evolution-studio`
- `web-research`
- `workspace-ops`
- `delivery-lab`
- `docs-foundry`
- `session-lab`

Bundled MCP surfaces 覆盖：

- docs search 与 repair
- workspace surface inspection
- release-readiness review
- session 与 approval forensics
- public-web research
- plugin 与 workflow design

当前 runtime surface：

- **26 builtin tools**
- **32 commands**
- **34 skills**
- **32 agents**
- **7 plugins**
- **10 MCP servers**
- **29 MCP tools / 27 MCP resources / 10 MCP prompts**

---

## 📚 文档

- [Architecture](./docs/architecture.md)
- [Feature Matrix (zh-CN)](./docs/feature-matrix.zh-CN.md)
- [Project Positioning (zh-CN)](./docs/project-positioning.zh-CN.md)
- [Roadmap (zh-CN)](./docs/roadmap.zh-CN.md)
- [OpenHarness Reference](./docs/openharness-reference.md)

---

## 📝 引用

如果你希望将 EvoHarness 作为软件系统引用：

```bibtex
@software{evoharness2026,
  title  = {EvoHarness: A Terminal-Native Agent Harness with Controlled Self-Evolution},
  author = {EvoHarness Contributors},
  year   = {2026},
  url    = {https://github.com/HITSZ-DS/EvoHarness}
}
```

同时也提供了 [CITATION.cff](./CITATION.cff)。

---

## 📄 License

Apache-2.0，见 [LICENSE](./LICENSE)。
