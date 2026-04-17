from __future__ import annotations

import fnmatch
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from evo_harness.harness.plugins import load_workspace_plugins
from evo_harness.harness.settings import HarnessSettings, load_settings


@dataclass(slots=True)
class HookDefinition:
    event: str
    path: str
    hook_type: str = "command"
    command: str | None = None
    matcher: str | None = None
    action: str = "allow"
    message: str = ""
    block_on_failure: bool = False
    timeout_seconds: int = 10
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class HookResult:
    hook_path: str
    success: bool
    blocked: bool
    output: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_workspace_hooks(workspace: str | Path, settings: HarnessSettings | None = None) -> list[HookDefinition]:
    root = Path(workspace).resolve()
    settings = settings or load_settings(workspace=root)
    hooks: list[HookDefinition] = []
    for pattern in (".openharness/hooks/*.json", ".claude/hooks/*.json", "hooks/*.json"):
        for path in sorted(root.glob(pattern)):
            hooks.extend(_hooks_from_json_path(path))
    for plugin in load_workspace_plugins(root, settings=settings):
        plugin_root = Path(plugin.path)
        direct_hooks = plugin_root / plugin.manifest.hooks_file
        if direct_hooks.exists():
            hooks.extend(_hooks_from_json_path(direct_hooks, source_prefix=f"plugin:{plugin.manifest.name}:", plugin_root=plugin_root))
        hooks_dir = plugin_root / plugin.manifest.hooks_dir
        if hooks_dir.exists():
            for path in sorted(hooks_dir.glob("*.json")):
                hooks.extend(
                    _hooks_from_json_path(path, source_prefix=f"plugin:{plugin.manifest.name}:", plugin_root=plugin_root)
                )
    return hooks


class HookExecutor:
    def __init__(self, hooks: list[HookDefinition]) -> None:
        self._hooks = hooks

    def matching(self, event: str, payload: dict[str, Any] | None = None) -> list[HookDefinition]:
        payload = payload or {}
        tool_name = str(payload.get("tool_name", ""))
        matches: list[HookDefinition] = []
        for hook in self._hooks:
            if hook.event != event:
                continue
            if hook.matcher and tool_name and not fnmatch.fnmatch(tool_name, hook.matcher):
                continue
            matches.append(hook)
        return matches

    def execute(self, event: str, payload: dict[str, Any], *, cwd: str | Path) -> list[HookResult]:
        results: list[HookResult] = []
        for hook in self.matching(event, payload):
            if hook.hook_type == "rule":
                blocked = hook.action == "deny"
                rendered = _render_message(hook.message or hook.description or "Rule hook matched.", payload)
                results.append(
                    HookResult(
                        hook_path=hook.path,
                        success=not blocked,
                        blocked=blocked,
                        output=rendered,
                        reason=rendered,
                    )
                )
                continue
            if hook.hook_type == "prompt":
                rendered = _render_message(hook.message or hook.description or "Prompt hook matched.", payload)
                results.append(
                    HookResult(
                        hook_path=hook.path,
                        success=True,
                        blocked=False,
                        output=rendered,
                        reason=rendered,
                    )
                )
                continue
            if hook.command is None:
                results.append(
                    HookResult(
                        hook_path=hook.path,
                        success=True,
                        blocked=False,
                        output="No command configured; metadata-only hook.",
                    )
                )
                continue

            process = subprocess.run(
                hook.command,
                cwd=str(Path(cwd).resolve()),
                shell=True,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=hook.timeout_seconds,
                env={
                    **os.environ,
                    "EVO_HARNESS_HOOK_EVENT": event,
                    "EVO_HARNESS_HOOK_PAYLOAD": json.dumps(payload, ensure_ascii=True),
                },
            )
            output = "\n".join(part for part in [process.stdout.strip(), process.stderr.strip()] if part)
            success = process.returncode == 0
            results.append(
                HookResult(
                    hook_path=hook.path,
                    success=success,
                    blocked=hook.block_on_failure and not success,
                    output=output,
                    reason=output or f"Hook exited with code {process.returncode}",
                )
            )
        return results


def _hooks_from_json_path(
    path: Path,
    *,
    source_prefix: str = "",
    plugin_root: Path | None = None,
) -> list[HookDefinition]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    hooks: list[HookDefinition] = []

    if isinstance(raw, dict) and "hooks" in raw and isinstance(raw["hooks"], list):
        for item in raw["hooks"]:
            hooks.append(_hook_from_item(item, path, source_prefix=source_prefix, plugin_root=plugin_root))
        return hooks

    if isinstance(raw, dict) and all(isinstance(value, list) for value in raw.values()):
        for event, entries in raw.items():
            for entry in entries:
                if isinstance(entry, dict) and isinstance(entry.get("hooks"), list):
                    matcher = entry.get("matcher")
                    for nested in entry.get("hooks", []):
                        nested_item = {
                            "event": event,
                            "matcher": matcher,
                            **dict(nested),
                        }
                        hooks.append(
                            _hook_from_item(
                                nested_item,
                                path,
                                source_prefix=source_prefix,
                                plugin_root=plugin_root,
                            )
                        )
                else:
                    item = {"event": event, **dict(entry)}
                    hooks.append(
                        _hook_from_item(
                            item,
                            path,
                            source_prefix=source_prefix,
                            plugin_root=plugin_root,
                        )
                    )
        return hooks

    if isinstance(raw, list):
        for item in raw:
            hooks.append(_hook_from_item(item, path, source_prefix=source_prefix, plugin_root=plugin_root))
        return hooks

    hooks.append(_hook_from_item(raw, path, source_prefix=source_prefix, plugin_root=plugin_root))
    return hooks


def _hook_from_item(
    item: dict[str, Any],
    path: Path,
    *,
    source_prefix: str,
    plugin_root: Path | None,
) -> HookDefinition:
    command = item.get("command")
    if isinstance(command, str) and plugin_root is not None:
        command = command.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_root))
        command = command.replace("${EVO_PLUGIN_ROOT}", str(plugin_root))
    return HookDefinition(
        event=str(item.get("event", "Unknown")),
        path=f"{source_prefix}{path}",
        hook_type=str(item.get("type", item.get("hook_type", "command"))),
        command=command,
        matcher=item.get("matcher"),
        action=str(item.get("action", "allow")),
        message=str(item.get("message", "")),
        block_on_failure=bool(item.get("block_on_failure", False)),
        timeout_seconds=int(item.get("timeout_seconds", 10)),
        description=str(item.get("description", "")),
    )


def _render_message(template: str, payload: dict[str, Any]) -> str:
    text = template
    for key, value in payload.items():
        text = text.replace("{" + key + "}", str(value))
    return text
