# 能力矩阵

说明：

- `已实现`：当前仓库已经有代码和测试支撑
- `基础版`：已有入口或骨架，但还不够强
- `未实现`：还没有真正做出来
- `目标`：这一列表示我们希望最终达到的工程强度

| 能力 | Claude Code 范式 | OpenHarness | 当前 Evo Harness | 我们的目标 |
|---|---|---|---|---|
| 终端优先工作方式 | 强 | 强 | 基础版 | 强 |
| `CLAUDE.md` / 项目指令加载 | 强 | 强 | 已实现 | 更强 |
| memory 文件体系 | 强 | 中 | 已实现 | 更强 |
| skills 加载 | 强 | 强 | 已实现 | 更强 |
| hooks 机制 | 强 | 强 | 已实现 | 更强 |
| permission / sandbox 思路 | 强 | 强 | 已实现基础版 | 更强 |
| settings hierarchy | 强 | 中 | 基础版 | 更强 |
| slash commands / workflow packaging | 强 | 中 | 已实现基础版 | 更强 |
| command-level allowed-tools enforcement | 强 | 部分 | 已实现 | 更强 |
| plugin discovery / packaging | 强 | 强 | 已实现基础版 | 更强 |
| agents / subagent discovery | 强 | 中 | 已实现基础版 | 更强 |
| subagent execution | 强 | 中 | 已实现基础版 | 更强 |
| subagents / delegation | 强 | 中 | 未实现 | 更强 |
| background task orchestration | 强 | 强 | 已实现基础版 | 更强 |
| task lifecycle controls | 强 | 强 | 已实现基础版 | 更强 |
| workflow orchestration | 强 | 中 | 已实现基础版 | 更强 |
| managed settings / org policy | 强 | 中 | 已实现基础版 | 更强 |
| marketplace discovery | 强 | 强 | 已实现基础版 | 更强 |
| session persistence | 强 | 中 | 已实现 | 更强 |
| query loop / tool loop | 强 | 强 | 已实现 provider-driven 基础版 | 更强 |
| 长回合稳定保护 | 强 | 强 | 已实现基础版 | 更强 |
| query stream / conversation resume | 强 | 强 | 已实现基础版 | 更强 |
| runtime tool registry | 强 | 强 | 已实现基础版 | 更强 |
| live model provider | 强 | 强 | 已实现基础版 | 更强 |
| plugin ecosystem | 强 | 中 | 已实现基础版 | 更强 |
| workspace status inspection | 中 | 中 | 已实现 | 更强 |
| system prompt assembly | 强 | 强 | 已实现 | 更强 |
| self-evolution planning | 弱/隐式 | 弱/隐式 | 已实现 | 强 |
| validation-first evolution | 弱/隐式 | 弱/隐式 | 已实现 | 强 |
| evolution ledger | 弱/隐式 | 弱/隐式 | 已实现 | 强 |
| capability-aware evolution | 弱/隐式 | 弱/隐式 | 已实现 | 强 |
| controlled evolution promotion | 弱/隐式 | 弱/隐式 | 已实现基础版 | 强 |
| promotion scoring / history report | 弱/隐式 | 弱/隐式 | 已实现基础版 | 强 |
| delegation tree / nested workflow | 强 | 中 | 已实现基础版 | 更强 |

## 当前结论

如果按“完整 harness 工程”来评价，当前 `Evo Harness` 还**不能**说已经超过 `OpenHarness`。

但如果按“harness + self-evolution control 一体化方向”来评价，当前仓库已经开始形成自己的独特价值：

- 它已经开始具备真正的 runtime 结构
- 它有 workspace-native commands / tools / hooks / sessions
- 它的 command policy 已经会真实约束工具调用
- 它已经有 manifest-based plugin discovery
- 它已经有 workspace/plugin agents discovery
- 它已经有 background shell/agent task orchestration
- 它已经有 workflow orchestration
- 它已经有 managed settings 和 marketplace discovery
- 它已经有 live provider 的工程入口
- 它已经有长回合保护和 delegation tree 的雏形
- 它已经能从真实 session 直接推导 evolution plan
- 它已经能把 evolution 以 candidate/apply/promote 方式受控执行
- 它显式把 `evolution planning / validation / ledger` 放进系统核心
- 它开始兼容 Claude Code 和 OpenHarness 两侧的工程范式

## 接下来最关键的缺口

如果你要认真冲“至少在 harness 上比 OpenHarness 更强”，后面必须补的不是小功能，而是这几个硬骨头：

1. 更强的模型驱动 `query loop`
2. 更完整的 `tool registry`
3. 更完整的 `command / plugin / subagent` 生态
4. 更完整的 settings hierarchy
5. 更强的 safety + rollback + promotion gating 机制
6. 把 self-evolution 和 runtime 闭环进一步做深

## 我建议的主线

不是先追求“功能点数量更多”，而是先让下面这条链路打通：

`workspace -> prompt -> tools -> execution -> validation -> evolution -> ledger`

一旦这条链打通，后面再加 commands、plugins、subagents，项目会越来越像真正的平台，而不是功能拼盘。
