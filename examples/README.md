# EvoHarness 配置示例

这个目录包含了各种 Provider 的配置示例文件。

## 📁 文件说明

### 本地/免费方案

- **`settings-claude-code-cli.json`** - 使用本地 Claude Code CLI
  - 需要：已安装并登录 Claude Code CLI
  - 成本：使用你的 Claude Code 订阅
  - 能力：完整的 Claude Sonnet 4 能力

- **`settings-ollama-llama3.json`** - 使用 Ollama + Llama 3
  - 需要：本地运行 Ollama，已下载 llama3 模型
  - 成本：完全免费
  - 能力：开源模型，适合一般任务

- **`settings-ollama-qwen2.json`** - 使用 Ollama + 通义千问 2
  - 需要：本地运行 Ollama，已下载 qwen2 模型
  - 成本：完全免费
  - 能力：中文支持好，适合中文任务

### API 方案

- **`settings-codex.json`** - 使用 OpenAI Codex
  - 需要：OpenAI API key
  - 成本：按使用付费
  - 能力：专门针对代码优化

## 🚀 使用方法

### 方法 1: 直接复制配置文件

```bash
# 复制你想要的配置到 .evo-harness/settings.json
cp examples/settings-ollama-llama3.json .evo-harness/settings.json

# 启动 EvoHarness
evoh --workspace .
```

### 方法 2: 使用 evoh init

```bash
# Claude Code CLI
evoh init --workspace . --provider-profile claude-code-cli --model claude-sonnet-4

# Ollama + Llama 3
evoh init --workspace . --provider-profile ollama --model llama3 --base-url http://localhost:11434/v1/chat/completions

# Ollama + 通义千问 2
evoh init --workspace . --provider-profile ollama --model qwen2 --base-url http://localhost:11434/v1/chat/completions

# OpenAI Codex
evoh init --workspace . --provider-profile codex --model gpt-4 --api-key-env OPENAI_API_KEY
```

### 方法 3: 在会话中使用 /setup

启动 EvoHarness 后，运行：

```
/setup
```

然后按照提示选择 provider、model 等。

## 📋 前置条件

### 使用 Claude Code CLI

1. 安装 Claude Code CLI：
   ```bash
   # 参考 https://docs.anthropic.com/claude/docs/claude-code
   ```

2. 登录：
   ```bash
   claude auth login
   ```

3. 验证：
   ```bash
   claude auth status
   ```

### 使用 Ollama

1. 安装 Ollama：
   ```bash
   # 下载地址: https://ollama.ai
   ```

2. 启动 Ollama（通常会自动启动）

3. 下载模型：
   ```bash
   # Llama 3
   ollama pull llama3
   
   # 通义千问 2
   ollama pull qwen2
   
   # 其他模型
   ollama pull codellama
   ollama pull mistral
   ```

4. 验证：
   ```bash
   ollama list
   curl http://localhost:11434/api/tags
   ```

### 使用 OpenAI Codex

1. 获取 API key：https://platform.openai.com/api-keys

2. 设置环境变量：
   ```bash
   export OPENAI_API_KEY="your-api-key-here"
   ```

## 💡 推荐配置

**最佳性能 + 成本平衡：**
```bash
# 主要工作用 Claude Code CLI
evoh init --workspace . --provider-profile claude-code-cli --model claude-sonnet-4

# 简单任务用 Ollama
evoh init --workspace . --provider-profile ollama --model llama3 --base-url http://localhost:11434/v1/chat/completions
```

**完全免费方案：**
```bash
# 中文任务
evoh init --workspace . --provider-profile ollama --model qwen2 --base-url http://localhost:11434/v1/chat/completions

# 代码任务
evoh init --workspace . --provider-profile ollama --model codellama --base-url http://localhost:11434/v1/chat/completions
```

## 🔧 故障排除

详见 [LOCAL_PROVIDERS.md](../LOCAL_PROVIDERS.md)
