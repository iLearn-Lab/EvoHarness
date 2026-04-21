# 本地 Provider 使用指南

EvoHarness 现在支持三种本地/低成本的 Provider，让你不再依赖昂贵的 API key！

## 🚀 支持的本地 Provider

### 1. Claude Code CLI（推荐）

使用你本地安装的 Claude Code CLI，利用你的 Claude Code 订阅而不是单独的 API key。

**配置方法：**

```bash
evoh init --workspace . --provider-profile claude-code-cli --model claude-sonnet-4
```

或者在会话中使用 `/setup`：
- Provider profile: `claude-code-cli`
- Model: `claude-sonnet-4` 或其他 Claude 模型
- API key: 留空（不需要）
- Base URL: 留空（不需要）

**前提条件：**
- 已安装 Claude Code CLI（`claude` 命令可用）
- 已登录 Claude Code（运行 `claude auth login`）

**优点：**
- 使用你的 Claude Code 订阅，不需要额外的 API key
- 完整的 Claude 能力
- 本地运行，响应快

---

### 2. Ollama（完全免费）

使用本地运行的开源模型，完全免费但能力可能较弱。

**配置方法：**

```bash
# 首先安装并启动 Ollama
# 下载地址: https://ollama.ai

# 拉取一个模型（例如 Llama 3）
ollama pull llama3

# 配置 EvoHarness
evoh init --workspace . --provider-profile ollama --model llama3 --base-url http://localhost:11434/v1/chat/completions
```

或者在会话中使用 `/setup`：
- Provider profile: `ollama`
- Model: `llama3`、`qwen2`、`mistral` 等
- API key: 留空（不需要）
- Base URL: `http://localhost:11434/v1/chat/completions`

**支持的模型：**
- `llama3` - Meta 的 Llama 3
- `qwen2` - 阿里的通义千问 2
- `mistral` - Mistral AI 的模型
- `codellama` - 专门用于代码的 Llama
- 更多模型见：https://ollama.ai/library

**优点：**
- 完全免费
- 数据不离开本地
- 支持多种开源模型

**缺点：**
- 需要较好的硬件（建议 16GB+ RAM）
- 能力可能不如 Claude/GPT

---

### 3. OpenAI Codex

如果你有 OpenAI Codex 的访问权限，可以使用它。

**配置方法：**

```bash
evoh init --workspace . --provider-profile codex --model codex-davinci-002 --api-key-env OPENAI_API_KEY
```

或者在会话中使用 `/setup`：
- Provider profile: `codex`
- Model: `codex-davinci-002` 或其他 Codex 模型
- API key: 你的 OpenAI API key
- Base URL: `https://api.openai.com/v1/chat/completions`

**注意：**
- 仍然需要 API key
- Codex 专门针对代码优化
- 可能比通用 GPT 模型更便宜

---

## 📝 配置示例

### 示例 1: 使用 Claude Code CLI

`.evo-harness/settings.json`:
```json
{
  "model": "claude-sonnet-4",
  "provider": {
    "provider": "claude-code-cli",
    "profile": "claude-code-cli",
    "api_format": "claude-cli",
    "cli_command": "claude"
  }
}
```

### 示例 2: 使用 Ollama + Llama 3

`.evo-harness/settings.json`:
```json
{
  "model": "llama3",
  "provider": {
    "provider": "ollama",
    "profile": "ollama",
    "api_format": "openai-chat",
    "base_url": "http://localhost:11434/v1/chat/completions"
  }
}
```

### 示例 3: 使用 Ollama + 通义千问 2

`.evo-harness/settings.json`:
```json
{
  "model": "qwen2",
  "provider": {
    "provider": "ollama",
    "profile": "ollama",
    "api_format": "openai-chat",
    "base_url": "http://localhost:11434/v1/chat/completions"
  }
}
```

---

## 🔧 故障排除

### Claude Code CLI 不工作

1. 检查 CLI 是否安装：
   ```bash
   claude --version
   ```

2. 检查是否已登录：
   ```bash
   claude auth status
   ```

3. 如果未登录，运行：
   ```bash
   claude auth login
   ```

### Ollama 不工作

1. 检查 Ollama 是否运行：
   ```bash
   curl http://localhost:11434/api/tags
   ```

2. 检查模型是否已下载：
   ```bash
   ollama list
   ```

3. 如果模型未下载：
   ```bash
   ollama pull llama3
   ```

### 性能优化

**对于 Ollama：**
- 使用较小的模型（如 `llama3:8b` 而不是 `llama3:70b`）
- 确保有足够的 RAM
- 考虑使用 GPU 加速

**对于 Claude Code CLI：**
- 确保网络连接稳定
- 增加 `request_timeout_seconds` 如果遇到超时

---

## 💡 推荐配置

**最佳性能 + 成本平衡：**
- 主要工作：Claude Code CLI（使用订阅）
- 简单任务：Ollama + llama3（完全免费）

**完全免费方案：**
- Ollama + qwen2（中文支持好）
- Ollama + codellama（代码任务）

**最佳代码能力：**
- Claude Code CLI + claude-sonnet-4
- OpenAI Codex（如果有访问权限）

---

## 📚 更多信息

- EvoHarness 文档：[README.md](./README.md)
- Ollama 官网：https://ollama.ai
- Claude Code 文档：https://docs.anthropic.com/claude/docs/claude-code
