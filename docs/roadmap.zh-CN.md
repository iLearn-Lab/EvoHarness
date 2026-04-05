# 路线图

## v0.1

目标：先把 `harness + self-evolution control` 的最小闭环站住。

- 支持 `OpenHarness` 风格 capability manifest
- 支持 Claude/OpenHarness 风格 workspace 发现
- 支持 `revise_skill`
- 支持 `distill_memory`
- 支持 `stop`
- 支持 validation 计划
- 支持 JSONL ledger
- 支持 demo 和基础测试

## v0.2

目标：让这个项目开始真的“能接更多 harness”。

- 加 `Claude Code` 风格 adapter
- 加更完整的 settings / permission 映射
- 加 workspace patch proposal 输出
- 加 replay result ingest
- 加 ledger summary CLI
- 加更多示例 workspace

## v0.3

目标：让它变成真正能拿来用的工程工具。

- 加 `consolidate_memory`
- 加 `forget_bad_memory`
- 加 rollback lineage
- 加 session lineage
- 加 operator policy plugin
- 加 dashboard-ready export

## v0.4

目标：从“单次计划器”走向“长期控制器”。

- 多 session 聚合分析
- 子代理感知的 evolution policy
- harness 间对比
- budget-aware policy
- risk-aware gating
- more reliable promotion checks

## 长期方向

- 跨 harness 的统一自进化评测
- 在线 verifier 接入
- 更完整的 operator space
- 更稳定的 autonomous evolution loop
- 成为 agent harness 生态中的通用 self-evolution layer

