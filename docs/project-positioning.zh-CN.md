# 项目定位

## 一句话定位

`Evo Harness` 是一个**面向 Agent Harness 的自进化控制层**。

它不替代 Claude Code、OpenHarness 或其他 agent runtime。
它的职责是建立在这些 harness 之上，负责：

- 观察一次真实执行
- 分析这次执行是否暴露了可复用改进信号
- 选择进化动作
- 给出验证计划
- 记录进化账本

## 为什么这个项目有工程意义

很多“自进化 agent”项目的问题不在于 idea 不好，而在于工程落点太虚。

常见问题包括：

- 没有真实 harness，只是 prompt loop
- 没有明确 workspace 约定
- 没有权限与安全边界
- 没有可审计变更
- 没有 rollback
- 没有长期 ledger

所以它们更像“会多试几次”的 agent，而不是可以在工程系统里长期运行的自进化能力层。

`Evo Harness` 反过来做：

- 先承认 harness 工程是第一位
- 再把自进化建成 harness 的控制层

## 这个项目参考了什么

### Claude Code 侧

我们参考的是它公开出来的工程范式，而不是空泛地说“像 Claude Code”：

- `CLAUDE.md` 作为项目级持续指令
- hook 机制
- settings hierarchy
- permission rules
- slash command 生态
- subagent / delegation 思路
- plugin 目录结构

### OpenHarness 侧

我们参考的是它公开源码里更完整的 harness core：

- query engine
- permission checker
- memory manager
- skill loader
- hook executor
- session storage
- task manager

## 这个项目真正解决什么

它解决的不是“模型会不会自动反思”。

它解决的是：

> 在一个真实的 agent harness 上，系统能否基于真实运行痕迹，判断何时值得进化、进化哪个对象、以及何时应该停止进化。

## 工程北极星

如果这个项目做对了，它应该具备下面这些特征：

- 能挂接到不同 harness，而不是绑死一个 runtime
- 能直接利用现有 workspace 约定，而不是强迫用户迁移
- 每次进化都有明确理由、目标、验证计划和账本记录
- 用户可以把它当工具层，而不是重新学习一个大平台
- 即使自进化失败，也不会把系统变得更难审计

## 产品边界

第一阶段我们不做：

- 完整 runtime 替代
- 参数级自更新
- 超多 operator 一次性全上
- “全自动无限循环”的黑盒 agent

第一阶段我们要做的是：

- 基于真实 harness 的最小闭环
- 把 `revise_skill / distill_memory / stop` 做扎实
- 让 ledger、validation、rollback 站住

## 为什么它可能有影响力

因为它不是只服务一种 agent。

只要一个系统满足下面条件，就有机会接入：

- 有工具调用
- 有 workspace
- 有持久 memory 或 skill
- 有执行痕迹
- 有验证手段

所以它可以用于：

- coding agent
- 内部自动化 agent
- 插件化团队 assistant
- 长期运行的 workflow agent
- 有 subagent 的多代理系统

这也是它最值得坚持的地方：

> 把自进化从“某个 prompt 技巧”变成“可挂接、可验证、可审计的 harness 工程能力”。

