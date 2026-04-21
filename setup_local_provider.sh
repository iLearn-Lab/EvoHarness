#!/bin/bash
# 快速配置 EvoHarness 本地 Provider

echo "=========================================="
echo "EvoHarness 本地 Provider 快速配置"
echo "=========================================="
echo ""

echo "请选择你想使用的 Provider:"
echo ""
echo "1) Claude Code CLI (使用你的 Claude Code 订阅)"
echo "2) Ollama + Llama 3 (完全免费)"
echo "3) Ollama + 通义千问 2 (完全免费，中文支持好)"
echo "4) OpenAI Codex (需要 API key)"
echo ""

read -p "请输入选项 (1-4): " choice

case $choice in
  1)
    echo ""
    echo "配置 Claude Code CLI..."
    echo ""

    # 检查 claude 命令是否存在
    if ! command -v claude &> /dev/null; then
      echo "❌ 错误: 未找到 claude 命令"
      echo "请先安装 Claude Code CLI: https://docs.anthropic.com/claude/docs/claude-code"
      exit 1
    fi

    # 检查是否已登录
    if ! claude auth status &> /dev/null; then
      echo "❌ 错误: 未登录 Claude Code"
      echo "请运行: claude auth login"
      exit 1
    fi

    echo "✅ Claude Code CLI 已就绪"
    echo ""
    echo "复制配置文件..."
    cp examples/settings-claude-code-cli.json .evo-harness/settings.json
    echo "✅ 配置完成！"
    echo ""
    echo "运行 'evoh --workspace .' 开始使用"
    ;;

  2)
    echo ""
    echo "配置 Ollama + Llama 3..."
    echo ""

    # 检查 Ollama 是否运行
    if ! curl -s http://localhost:11434/api/tags &> /dev/null; then
      echo "❌ 错误: Ollama 未运行"
      echo "请先安装并启动 Ollama: https://ollama.ai"
      exit 1
    fi

    # 检查 llama3 模型是否存在
    if ! ollama list | grep -q llama3; then
      echo "⚠️  警告: llama3 模型未安装"
      echo "正在下载 llama3 模型（这可能需要几分钟）..."
      ollama pull llama3
    fi

    echo "✅ Ollama + Llama 3 已就绪"
    echo ""
    echo "复制配置文件..."
    cp examples/settings-ollama-llama3.json .evo-harness/settings.json
    echo "✅ 配置完成！"
    echo ""
    echo "运行 'evoh --workspace .' 开始使用"
    ;;

  3)
    echo ""
    echo "配置 Ollama + 通义千问 2..."
    echo ""

    # 检查 Ollama 是否运行
    if ! curl -s http://localhost:11434/api/tags &> /dev/null; then
      echo "❌ 错误: Ollama 未运行"
      echo "请先安装并启动 Ollama: https://ollama.ai"
      exit 1
    fi

    # 检查 qwen2 模型是否存在
    if ! ollama list | grep -q qwen2; then
      echo "⚠️  警告: qwen2 模型未安装"
      echo "正在下载 qwen2 模型（这可能需要几分钟）..."
      ollama pull qwen2
    fi

    echo "✅ Ollama + 通义千问 2 已就绪"
    echo ""
    echo "复制配置文件..."
    cp examples/settings-ollama-qwen2.json .evo-harness/settings.json
    echo "✅ 配置完成！"
    echo ""
    echo "运行 'evoh --workspace .' 开始使用"
    ;;

  4)
    echo ""
    echo "配置 OpenAI Codex..."
    echo ""

    # 检查 API key
    if [ -z "$OPENAI_API_KEY" ]; then
      echo "⚠️  警告: 未设置 OPENAI_API_KEY 环境变量"
      echo "请先设置: export OPENAI_API_KEY='your-api-key'"
      echo ""
      read -p "是否继续配置? (y/n): " continue
      if [ "$continue" != "y" ]; then
        exit 0
      fi
    fi

    echo "复制配置文件..."
    cp examples/settings-codex.json .evo-harness/settings.json
    echo "✅ 配置完成！"
    echo ""
    echo "运行 'evoh --workspace .' 开始使用"
    ;;

  *)
    echo "❌ 无效的选项"
    exit 1
    ;;
esac

echo ""
echo "=========================================="
echo "📚 更多信息:"
echo "  - 详细文档: LOCAL_PROVIDERS.md"
echo "  - 配置示例: examples/README.md"
echo "  - 测试脚本: python test_local_providers.py"
echo "=========================================="
