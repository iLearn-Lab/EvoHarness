from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PathRule:
    pattern: str
    allow: bool = True


@dataclass(slots=True)
class PermissionSettings:
    mode: str = "default"
    allowed_tools: list[str] = field(default_factory=list)
    denied_tools: list[str] = field(default_factory=list)
    path_rules: list[PathRule] = field(default_factory=list)
    denied_commands: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProviderSettings:
    provider: str = "anthropic"
    profile: str = "auto"
    api_format: str = "auto"
    api_key: str | None = None
    api_key_env: str = "ANTHROPIC_API_KEY"
    base_url: str = "https://api.anthropic.com/v1/messages"
    model_env: str | None = None
    auth_scheme: str = "x-api-key"
    headers: dict[str, str] = field(default_factory=dict)
    anthropic_version: str = "2023-06-01"
    max_turns: int = 8
    max_consecutive_tool_rounds: int = 4
    max_repeated_tool_call_signatures: int = 2
    max_empty_assistant_turns: int = 2


@dataclass(slots=True)
class QueryLoopSettings:
    max_turns: int = 8
    max_consecutive_tool_rounds: int = 4
    max_repeated_tool_call_signatures: int = 2
    max_empty_assistant_turns: int = 2
    max_total_tool_calls: int = 24
    max_tool_failures: int = 6
    max_parallel_tool_calls: int = 4
    max_context_messages: int = 24
    max_context_chars: int = 120000
    max_repeated_assistant_turns: int = 2


@dataclass(slots=True)
class PromotionPolicySettings:
    min_executed_validations: int = 1
    max_recent_failed_promotions: int = 1
    require_executed_regression: bool = True
    allow_auto_promote: bool = True
    min_promotion_score: float = 0.55
    require_candidate_before_promotion: bool = True
    cooldown_seconds: int = 0


@dataclass(slots=True)
class ManagedSettings:
    allow_managed_hooks_only: bool = False
    allow_managed_permission_rules_only: bool = False
    strict_known_marketplaces: list[dict[str, Any]] = field(default_factory=list)
    extra_known_marketplaces: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class SafetySettings:
    blocked_shell_patterns: list[str] = field(
        default_factory=lambda: [
            "*rm -rf*",
            "*del /f*",
            "*format *",
            "*shutdown *",
            "*mkfs*",
        ]
    )
    destructive_tools: list[str] = field(
        default_factory=lambda: [
            "write_file",
            "replace_in_file",
            "write_json",
            "delete_path",
            "make_dir",
            "bash",
            "run_command",
        ]
    )
    max_mutating_tools_per_query: int = 12
    max_mutating_tool_failures: int = 4
    rollback_on_apply_validation_failure: bool = True


@dataclass(slots=True)
class SandboxSettings:
    mode: str = "workspace-write"
    writable_roots: list[str] = field(default_factory=list)
    readable_roots: list[str] = field(default_factory=list)
    allow_network: bool = True
    block_bash_by_default: bool = False


@dataclass(slots=True)
class ApprovalSettings:
    mode: str = "queue"
    cache_approved_actions: bool = True
    cache_denied_actions: bool = True
    fingerprint_fields: list[str] = field(default_factory=lambda: ["tool_name", "arguments", "command", "file_path"])


@dataclass(slots=True)
class RuntimeSettings:
    autosave_sessions: bool = True
    save_turn_events: bool = True
    max_session_messages: int = 400


@dataclass(slots=True)
class SubagentSettings:
    default_model: str | None = None
    default_max_turns: int = 6
    share_history: bool = True
    include_parent_summary: bool = True
    max_parallel: int = 4


@dataclass(slots=True)
class UiSettings:
    theme: str = "terminal"
    show_hints: bool = True
    show_query_metrics: bool = True
    dense: bool = False


@dataclass(slots=True)
class HarnessSettings:
    model: str = "claude-sonnet-4"
    max_tokens: int = 16384
    system_prompt: str | None = None
    provider: ProviderSettings = field(default_factory=ProviderSettings)
    query: QueryLoopSettings = field(default_factory=QueryLoopSettings)
    promotion: PromotionPolicySettings = field(default_factory=PromotionPolicySettings)
    managed: ManagedSettings = field(default_factory=ManagedSettings)
    permission: PermissionSettings = field(default_factory=PermissionSettings)
    safety: SafetySettings = field(default_factory=SafetySettings)
    sandbox: SandboxSettings = field(default_factory=SandboxSettings)
    approvals: ApprovalSettings = field(default_factory=ApprovalSettings)
    runtime: RuntimeSettings = field(default_factory=RuntimeSettings)
    subagents: SubagentSettings = field(default_factory=SubagentSettings)
    ui: UiSettings = field(default_factory=UiSettings)
    hooks: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    enabled_plugins: dict[str, bool] = field(default_factory=dict)
    plugin_settings: dict[str, dict[str, Any]] = field(default_factory=dict)
    mcp_servers: dict[str, dict[str, Any]] = field(default_factory=dict)
    memory_enabled: bool = True
    workspace_instructions: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["permission"]["path_rules"] = [asdict(rule) for rule in self.permission.path_rules]
        return payload


def get_default_settings_path() -> Path:
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    return home / ".evo-harness" / "settings.json"


def get_default_settings_dir() -> Path:
    return get_default_settings_path().with_name("settings.d")


def get_project_settings_path(workspace: str | Path) -> Path:
    return Path(workspace).resolve() / ".evo-harness" / "settings.json"


def get_project_local_settings_path(workspace: str | Path) -> Path:
    return Path(workspace).resolve() / ".evo-harness" / "settings.local.json"


def get_managed_settings_path(workspace: str | Path) -> Path:
    return Path(workspace).resolve() / ".evo-harness" / "managed-settings.json"


def get_managed_settings_dir(workspace: str | Path) -> Path:
    return Path(workspace).resolve() / ".evo-harness" / "managed-settings.d"


def load_settings(path: str | Path | None = None, *, workspace: str | Path | None = None) -> HarnessSettings:
    merged: dict[str, Any] = {}
    managed_raw: dict[str, Any] = {}

    merged = _deep_merge(merged, _load_one_settings_file(get_default_settings_path()))
    for extra_path in sorted(get_default_settings_dir().glob("*.json")) if get_default_settings_dir().exists() else []:
        merged = _deep_merge(merged, _load_one_settings_file(extra_path))

    if workspace is not None:
        merged = _deep_merge(merged, _load_one_settings_file(get_project_settings_path(workspace)))
        merged = _deep_merge(merged, _load_one_settings_file(get_project_local_settings_path(workspace)))

    if path is not None:
        merged = _deep_merge(merged, _load_one_settings_source(path))

    merged = _deep_merge(merged, _env_overrides())

    if workspace is not None:
        managed_raw = _deep_merge(managed_raw, _load_one_settings_file(get_managed_settings_path(workspace)))
        managed_dir = get_managed_settings_dir(workspace)
        if managed_dir.exists():
            for managed_file in sorted(managed_dir.glob("*.json")):
                managed_raw = _deep_merge(managed_raw, _load_one_settings_file(managed_file))
        merged = _deep_merge(merged, managed_raw)

    permission_raw = dict(merged.get("permission", {}))
    provider_raw = dict(merged.get("provider", {}))
    query_raw = dict(merged.get("query", {}))
    promotion_raw = dict(merged.get("promotion", {}))
    managed_settings_raw = dict(merged.get("managed", {}))
    safety_raw = dict(merged.get("safety", {}))
    sandbox_raw = dict(merged.get("sandbox", {}))
    approvals_raw = dict(merged.get("approvals", {}))
    runtime_raw = dict(merged.get("runtime", {}))
    subagents_raw = dict(merged.get("subagents", {}))
    ui_raw = dict(merged.get("ui", {}))

    permission = _permission_settings_from_raw(permission_raw)
    provider = ProviderSettings(
        provider=str(provider_raw.get("provider", "anthropic")),
        profile=str(provider_raw.get("profile", "auto")),
        api_format=str(provider_raw.get("api_format", "auto")),
        api_key=provider_raw.get("api_key"),
        api_key_env=str(provider_raw.get("api_key_env", "ANTHROPIC_API_KEY")),
        base_url=str(provider_raw.get("base_url", "https://api.anthropic.com/v1/messages")),
        model_env=provider_raw.get("model_env"),
        auth_scheme=str(provider_raw.get("auth_scheme", "x-api-key")),
        headers={str(key): str(value) for key, value in dict(provider_raw.get("headers", {})).items()},
        anthropic_version=str(provider_raw.get("anthropic_version", "2023-06-01")),
        max_turns=int(provider_raw.get("max_turns", 8)),
        max_consecutive_tool_rounds=int(provider_raw.get("max_consecutive_tool_rounds", 4)),
        max_repeated_tool_call_signatures=int(provider_raw.get("max_repeated_tool_call_signatures", 2)),
        max_empty_assistant_turns=int(provider_raw.get("max_empty_assistant_turns", 2)),
    )
    query = QueryLoopSettings(
        max_turns=int(query_raw.get("max_turns", provider.max_turns)),
        max_consecutive_tool_rounds=int(
            query_raw.get("max_consecutive_tool_rounds", provider.max_consecutive_tool_rounds)
        ),
        max_repeated_tool_call_signatures=int(
            query_raw.get("max_repeated_tool_call_signatures", provider.max_repeated_tool_call_signatures)
        ),
        max_empty_assistant_turns=int(query_raw.get("max_empty_assistant_turns", provider.max_empty_assistant_turns)),
        max_total_tool_calls=int(query_raw.get("max_total_tool_calls", 24)),
        max_tool_failures=int(query_raw.get("max_tool_failures", 6)),
        max_parallel_tool_calls=int(query_raw.get("max_parallel_tool_calls", 4)),
        max_context_messages=int(query_raw.get("max_context_messages", 24)),
        max_context_chars=int(query_raw.get("max_context_chars", 120000)),
        max_repeated_assistant_turns=int(query_raw.get("max_repeated_assistant_turns", 2)),
    )
    promotion = PromotionPolicySettings(
        min_executed_validations=int(promotion_raw.get("min_executed_validations", 1)),
        max_recent_failed_promotions=int(promotion_raw.get("max_recent_failed_promotions", 1)),
        require_executed_regression=bool(promotion_raw.get("require_executed_regression", True)),
        allow_auto_promote=bool(promotion_raw.get("allow_auto_promote", True)),
        min_promotion_score=float(promotion_raw.get("min_promotion_score", 0.55)),
        require_candidate_before_promotion=bool(promotion_raw.get("require_candidate_before_promotion", True)),
        cooldown_seconds=int(promotion_raw.get("cooldown_seconds", 0)),
    )
    managed = ManagedSettings(
        allow_managed_hooks_only=bool(managed_settings_raw.get("allow_managed_hooks_only", False)),
        allow_managed_permission_rules_only=bool(managed_settings_raw.get("allow_managed_permission_rules_only", False)),
        strict_known_marketplaces=list(managed_settings_raw.get("strict_known_marketplaces", [])),
        extra_known_marketplaces=list(managed_settings_raw.get("extra_known_marketplaces", [])),
    )
    if managed.allow_managed_permission_rules_only:
        permission = _permission_settings_from_raw(dict(managed_raw.get("permission", {})))

    safety = SafetySettings(
        blocked_shell_patterns=list(safety_raw.get("blocked_shell_patterns", SafetySettings().blocked_shell_patterns)),
        destructive_tools=list(safety_raw.get("destructive_tools", SafetySettings().destructive_tools)),
        max_mutating_tools_per_query=int(safety_raw.get("max_mutating_tools_per_query", 12)),
        max_mutating_tool_failures=int(safety_raw.get("max_mutating_tool_failures", 4)),
        rollback_on_apply_validation_failure=bool(safety_raw.get("rollback_on_apply_validation_failure", True)),
    )
    sandbox = SandboxSettings(
        mode=str(sandbox_raw.get("mode", "workspace-write")),
        writable_roots=[str(item) for item in sandbox_raw.get("writable_roots", [])],
        readable_roots=[str(item) for item in sandbox_raw.get("readable_roots", [])],
        allow_network=bool(sandbox_raw.get("allow_network", True)),
        block_bash_by_default=bool(sandbox_raw.get("block_bash_by_default", False)),
    )
    approvals = ApprovalSettings(
        mode=str(approvals_raw.get("mode", "queue")),
        cache_approved_actions=bool(approvals_raw.get("cache_approved_actions", True)),
        cache_denied_actions=bool(approvals_raw.get("cache_denied_actions", True)),
        fingerprint_fields=[str(item) for item in approvals_raw.get("fingerprint_fields", ["tool_name", "arguments", "command", "file_path"])],
    )
    runtime = RuntimeSettings(
        autosave_sessions=bool(runtime_raw.get("autosave_sessions", True)),
        save_turn_events=bool(runtime_raw.get("save_turn_events", True)),
        max_session_messages=int(runtime_raw.get("max_session_messages", 400)),
    )
    subagents = SubagentSettings(
        default_model=subagents_raw.get("default_model"),
        default_max_turns=int(subagents_raw.get("default_max_turns", 6)),
        share_history=bool(subagents_raw.get("share_history", True)),
        include_parent_summary=bool(subagents_raw.get("include_parent_summary", True)),
        max_parallel=int(subagents_raw.get("max_parallel", 4)),
    )
    ui = UiSettings(
        theme=str(ui_raw.get("theme", "terminal")),
        show_hints=bool(ui_raw.get("show_hints", True)),
        show_query_metrics=bool(ui_raw.get("show_query_metrics", True)),
        dense=bool(ui_raw.get("dense", False)),
    )

    return HarnessSettings(
        model=str(merged.get("model", "claude-sonnet-4")),
        max_tokens=int(merged.get("max_tokens", 16384)),
        system_prompt=merged.get("system_prompt"),
        provider=provider,
        query=query,
        promotion=promotion,
        managed=managed,
        permission=permission,
        safety=safety,
        sandbox=sandbox,
        approvals=approvals,
        runtime=runtime,
        subagents=subagents,
        ui=ui,
        hooks=dict(merged.get("hooks", {})),
        enabled_plugins=dict(merged.get("enabled_plugins", {})),
        plugin_settings=_normalize_plugin_settings(merged.get("plugin_settings", {})),
        mcp_servers=_normalize_plugin_settings(merged.get("mcp_servers", {})),
        memory_enabled=bool(merged.get("memory_enabled", True)),
        workspace_instructions=bool(merged.get("workspace_instructions", True)),
    )


def _permission_settings_from_raw(permission_raw: dict[str, Any]) -> PermissionSettings:
    return PermissionSettings(
        mode=str(permission_raw.get("mode", "default")),
        allowed_tools=list(permission_raw.get("allowed_tools", [])),
        denied_tools=list(permission_raw.get("denied_tools", [])),
        path_rules=[
            PathRule(pattern=item["pattern"], allow=bool(item.get("allow", True)))
            for item in permission_raw.get("path_rules", [])
            if isinstance(item, dict) and "pattern" in item
        ],
        denied_commands=list(permission_raw.get("denied_commands", [])),
    )


def _normalize_plugin_settings(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for name, value in raw.items():
        if isinstance(value, dict):
            normalized[str(name)] = dict(value)
    return normalized


def _load_one_settings_source(source: str | Path) -> dict[str, Any]:
    if isinstance(source, Path):
        return _load_one_settings_file(source)
    text = str(source).strip()
    if not text:
        return {}
    if text.startswith("{"):
        return json.loads(text)
    return _load_one_settings_file(Path(text))


def _load_one_settings_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _env_overrides() -> dict[str, Any]:
    raw: dict[str, Any] = {}
    direct_string_overrides = {
        "EVO_HARNESS_MODEL": ("model",),
        "EVO_HARNESS_SYSTEM_PROMPT": ("system_prompt",),
        "EVO_HARNESS_PROVIDER": ("provider", "provider"),
        "EVO_HARNESS_PROVIDER_PROFILE": ("provider", "profile"),
        "EVO_HARNESS_PROVIDER_FORMAT": ("provider", "api_format"),
        "EVO_HARNESS_API_KEY_ENV": ("provider", "api_key_env"),
        "EVO_HARNESS_PROVIDER_API_KEY": ("provider", "api_key"),
        "EVO_HARNESS_BASE_URL": ("provider", "base_url"),
        "EVO_HARNESS_AUTH_SCHEME": ("provider", "auth_scheme"),
        "EVO_HARNESS_PERMISSION_MODE": ("permission", "mode"),
        "EVO_HARNESS_SANDBOX_MODE": ("sandbox", "mode"),
        "EVO_HARNESS_APPROVAL_MODE": ("approvals", "mode"),
        "EVO_HARNESS_UI_THEME": ("ui", "theme"),
        "EVO_HARNESS_SUBAGENT_MODEL": ("subagents", "default_model"),
    }
    direct_int_overrides = {
        "EVO_HARNESS_MAX_TOKENS": ("max_tokens",),
        "EVO_HARNESS_QUERY_MAX_TURNS": ("query", "max_turns"),
        "EVO_HARNESS_QUERY_MAX_TOOL_CALLS": ("query", "max_total_tool_calls"),
        "EVO_HARNESS_QUERY_MAX_TOOL_FAILURES": ("query", "max_tool_failures"),
        "EVO_HARNESS_SUBAGENT_MAX_TURNS": ("subagents", "default_max_turns"),
    }
    direct_bool_overrides = {
        "EVO_HARNESS_MEMORY_ENABLED": ("memory_enabled",),
        "EVO_HARNESS_WORKSPACE_INSTRUCTIONS": ("workspace_instructions",),
        "EVO_HARNESS_AUTO_PROMOTE": ("promotion", "allow_auto_promote"),
        "EVO_HARNESS_UI_HINTS": ("ui", "show_hints"),
        "EVO_HARNESS_SANDBOX_ALLOW_NETWORK": ("sandbox", "allow_network"),
    }

    for env_name, key_path in direct_string_overrides.items():
        value = os.environ.get(env_name)
        if value:
            _assign_nested(raw, key_path, value)

    for env_name, key_path in direct_int_overrides.items():
        value = os.environ.get(env_name)
        if value:
            _assign_nested(raw, key_path, int(value))

    for env_name, key_path in direct_bool_overrides.items():
        value = os.environ.get(env_name)
        if value:
            _assign_nested(raw, key_path, _parse_bool(value))

    if os.environ.get("ANTHROPIC_API_KEY"):
        _assign_nested(raw, ("provider", "provider"), "anthropic")
        _assign_nested(raw, ("provider", "profile"), "anthropic")
        _assign_nested(raw, ("provider", "api_format"), "anthropic")
        _assign_nested(raw, ("provider", "api_key_env"), "ANTHROPIC_API_KEY")
    if os.environ.get("ANTHROPIC_BASE_URL"):
        _assign_nested(raw, ("provider", "base_url"), os.environ["ANTHROPIC_BASE_URL"])
    if os.environ.get("ANTHROPIC_MODEL"):
        raw["model"] = os.environ["ANTHROPIC_MODEL"]
    if os.environ.get("OPENAI_API_KEY"):
        _assign_nested(raw, ("provider", "provider"), "openai")
        _assign_nested(raw, ("provider", "profile"), "openai-compatible")
        _assign_nested(raw, ("provider", "api_format"), "openai-chat")
        _assign_nested(raw, ("provider", "api_key_env"), "OPENAI_API_KEY")
        _assign_nested(raw, ("provider", "auth_scheme"), "bearer")
    if os.environ.get("OPENAI_BASE_URL"):
        _assign_nested(raw, ("provider", "base_url"), os.environ["OPENAI_BASE_URL"])
    if os.environ.get("OPENAI_MODEL"):
        raw["model"] = os.environ["OPENAI_MODEL"]
    if os.environ.get("MOONSHOT_API_KEY"):
        _assign_nested(raw, ("provider", "provider"), "openai")
        _assign_nested(raw, ("provider", "profile"), "moonshot")
        _assign_nested(raw, ("provider", "api_format"), "openai-chat")
        _assign_nested(raw, ("provider", "api_key_env"), "MOONSHOT_API_KEY")
        _assign_nested(raw, ("provider", "auth_scheme"), "bearer")
    if os.environ.get("MOONSHOT_BASE_URL"):
        _assign_nested(raw, ("provider", "base_url"), os.environ["MOONSHOT_BASE_URL"])
    zhipu_key_env = next(
        (name for name in ("ZHIPUAI_API_KEY", "BIGMODEL_API_KEY", "GLM_API_KEY") if os.environ.get(name)),
        None,
    )
    if zhipu_key_env:
        _assign_nested(raw, ("provider", "provider"), "openai")
        _assign_nested(raw, ("provider", "profile"), "zhipu")
        _assign_nested(raw, ("provider", "api_format"), "openai-chat")
        _assign_nested(raw, ("provider", "api_key_env"), zhipu_key_env)
        _assign_nested(raw, ("provider", "auth_scheme"), "bearer")
    zhipu_base_url = os.environ.get("ZHIPUAI_BASE_URL") or os.environ.get("BIGMODEL_BASE_URL")
    if zhipu_base_url:
        _assign_nested(raw, ("provider", "base_url"), zhipu_base_url)

    return raw


def _assign_nested(raw: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cursor = raw
    for key in path[:-1]:
        next_value = cursor.get(key)
        if not isinstance(next_value, dict):
            next_value = {}
            cursor[key] = next_value
        cursor = next_value
    cursor[path[-1]] = value


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def save_settings(settings: HarnessSettings, path: str | Path | None = None) -> Path:
    settings_path = Path(path) if path else get_default_settings_path()
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings.to_dict(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return settings_path
