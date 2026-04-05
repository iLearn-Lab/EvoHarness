"""Harness-native runtime foundations for Evo Harness."""

from importlib import import_module

from .agents import AgentDefinition, find_agent, load_workspace_agents
from .approvals import ApprovalManager, ApprovalRequest
from .commands import CommandDefinition, find_command, load_workspace_commands
from .environment import EnvironmentInfo, get_environment_info
from .evolution_bridge import plan_from_saved_session, plan_from_session_snapshot, task_trace_from_session_snapshot
from .hooks import HookDefinition, HookExecutor, HookResult, load_workspace_hooks
from .memory import (
    add_memory_entry,
    find_relevant_memory_entries,
    list_memory_entries,
    load_memory_prompt,
    remove_memory_entry,
    render_memory_entry,
)
from .conversation import ConversationEngine
from .marketplaces import MarketplaceDefinition, MarketplacePlugin, install_marketplace_plugin, load_marketplaces
from .mcp import (
    McpPromptDefinition,
    McpRegistry,
    McpResourceDefinition,
    McpServerDefinition,
    McpToolDefinition,
    list_mcp_prompts,
    list_mcp_resources,
    list_mcp_servers,
    list_mcp_tools,
    load_mcp_registry,
)
from .mcp_runtime import (
    call_mcp_method,
    call_mcp_tool,
    get_mcp_prompt,
    list_mcp_runtime_prompts,
    list_mcp_runtime_resources,
    list_mcp_runtime_tools,
    read_mcp_resource,
)
from .messages import ChatMessage, ProviderTurn, ToolCall
from .permissions import PermissionChecker, PermissionDecision
from .plugins import LoadedPlugin, PluginManifest, discover_plugin_paths, load_workspace_plugins
from .prompts import build_system_prompt
from .provider import (
    AnthropicProvider,
    BaseProvider,
    OpenAIChatProvider,
    ProviderProfile,
    ScriptedProvider,
    build_live_provider,
    detect_provider_profile,
    list_provider_profiles,
)
from .query import QueryRunResult, run_query, run_query_stream
from .runtime import HarnessRuntime
from .session import (
    export_session_markdown,
    list_session_snapshots,
    load_session_snapshot,
    save_session_snapshot,
    session_analytics_report,
)
from .settings import (
    ApprovalSettings,
    HarnessSettings,
    PermissionSettings,
    ProviderSettings,
    QueryLoopSettings,
    RuntimeSettings,
    SandboxSettings,
    SafetySettings,
    SubagentSettings,
    UiSettings,
    load_settings,
    save_settings,
)
from .skills import SkillDefinition, load_workspace_skills
from .stream_events import AssistantTextDelta, AssistantTurnComplete, StreamEvent, ToolExecutionCompleted, ToolExecutionStarted
from .subagents import SubagentResult, run_subagent
from .tasks import TaskManager, TaskRecord, get_task_manager
from .tools import ToolExecutionContext, ToolRegistry, ToolResult, create_default_tool_registry
from .workflows import WorkflowDefinition, WorkflowResult, WorkflowStep, load_workflow, run_workflow


_LAZY_IMPORTS = {
    "BackendHostConfig": (".backend_host", "BackendHostConfig"),
    "ReactBackendHost": (".backend_host", "ReactBackendHost"),
    "run_backend_host": (".backend_host", "run_backend_host"),
    "build_backend_command": (".react_launcher", "build_backend_command"),
    "get_frontend_dir": (".react_launcher", "get_frontend_dir"),
    "launch_react_tui": (".react_launcher", "launch_react_tui"),
    "SlashCommand": (".slash_commands", "SlashCommand"),
    "SlashCommandContext": (".slash_commands", "SlashCommandContext"),
    "SlashCommandRegistry": (".slash_commands", "SlashCommandRegistry"),
    "SlashCommandResult": (".slash_commands", "SlashCommandResult"),
    "create_default_slash_command_registry": (".slash_commands", "create_default_slash_command_registry"),
    "format_prompt_label": (".slash_commands", "format_prompt_label"),
    "format_session_banner": (".slash_commands", "format_session_banner"),
    "HomeState": (".ui", "HomeState"),
    "build_home_state": (".ui", "build_home_state"),
    "render_home": (".ui", "render_home"),
    "run_home_ui": (".ui", "run_home_ui"),
    "run_interactive_repl": (".ui", "run_interactive_repl"),
}


def __getattr__(name: str):
    target = _LAZY_IMPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value

__all__ = [
    "CommandDefinition",
    "EnvironmentInfo",
    "AnthropicProvider",
    "AgentDefinition",
    "ApprovalManager",
    "ApprovalRequest",
    "ApprovalSettings",
    "AssistantTextDelta",
    "AssistantTurnComplete",
    "BaseProvider",
    "BackendHostConfig",
    "ChatMessage",
    "ConversationEngine",
    "HookDefinition",
    "HookExecutor",
    "HookResult",
    "HarnessSettings",
    "HarnessRuntime",
    "HomeState",
    "LoadedPlugin",
    "McpPromptDefinition",
    "McpRegistry",
    "McpResourceDefinition",
    "McpServerDefinition",
    "McpToolDefinition",
    "MarketplaceDefinition",
    "MarketplacePlugin",
    "PermissionChecker",
    "PermissionDecision",
    "PermissionSettings",
    "plan_from_saved_session",
    "plan_from_session_snapshot",
    "PluginManifest",
    "ProviderTurn",
    "ProviderProfile",
    "ProviderSettings",
    "QueryLoopSettings",
    "QueryRunResult",
    "ReactBackendHost",
    "RuntimeSettings",
    "SandboxSettings",
    "SafetySettings",
    "SlashCommand",
    "SlashCommandContext",
    "SlashCommandRegistry",
    "SlashCommandResult",
    "OpenAIChatProvider",
    "ScriptedProvider",
    "SkillDefinition",
    "SubagentSettings",
    "SubagentResult",
    "TaskManager",
    "TaskRecord",
    "ToolExecutionContext",
    "ToolCall",
    "ToolExecutionCompleted",
    "ToolExecutionStarted",
    "ToolRegistry",
    "ToolResult",
    "StreamEvent",
    "WorkflowDefinition",
    "WorkflowResult",
    "WorkflowStep",
    "UiSettings",
    "add_memory_entry",
    "find_relevant_memory_entries",
    "build_live_provider",
    "build_backend_command",
    "build_system_prompt",
    "create_default_slash_command_registry",
    "call_mcp_method",
    "call_mcp_tool",
    "create_default_tool_registry",
    "detect_provider_profile",
    "discover_plugin_paths",
    "export_session_markdown",
    "find_agent",
    "find_command",
    "format_prompt_label",
    "format_session_banner",
    "get_environment_info",
    "get_frontend_dir",
    "get_mcp_prompt",
    "list_memory_entries",
    "list_mcp_prompts",
    "list_mcp_resources",
    "list_mcp_servers",
    "list_mcp_tools",
    "list_mcp_runtime_prompts",
    "list_mcp_runtime_resources",
    "list_mcp_runtime_tools",
    "list_provider_profiles",
    "list_session_snapshots",
    "load_marketplaces",
    "load_memory_prompt",
    "load_mcp_registry",
    "load_workspace_commands",
    "load_workspace_plugins",
    "load_session_snapshot",
    "load_settings",
    "load_workspace_agents",
    "load_workspace_hooks",
    "load_workspace_skills",
    "remove_memory_entry",
    "render_memory_entry",
    "launch_react_tui",
    "run_backend_host",
    "run_interactive_repl",
    "run_query",
    "run_query_stream",
    "save_session_snapshot",
    "save_settings",
    "session_analytics_report",
    "read_mcp_resource",
    "install_marketplace_plugin",
    "get_task_manager",
    "load_workflow",
    "run_subagent",
    "run_workflow",
    "build_home_state",
    "render_home",
    "run_home_ui",
    "task_trace_from_session_snapshot",
]
