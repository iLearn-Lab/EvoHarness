from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from evo_harness.harness.settings import PermissionSettings, SandboxSettings


NETWORK_TOOLS = {"download_file", "web_fetch", "web_search", "mcp_call_tool", "mcp_read_resource", "mcp_get_prompt"}


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    requires_confirmation: bool = False
    reason: str = ""


class PermissionChecker:
    """Evaluate tool usage against configured permission mode, sandbox, and path rules."""

    def __init__(
        self,
        settings: PermissionSettings,
        *,
        sandbox: SandboxSettings | None = None,
        workspace: str | Path | None = None,
    ) -> None:
        self._settings = settings
        self._sandbox = sandbox or SandboxSettings()
        self._workspace = Path(workspace).resolve() if workspace is not None else None
        self._readable_roots = self._resolve_roots(self._sandbox.readable_roots, include_workspace=True)
        self._writable_roots = self._resolve_roots(self._sandbox.writable_roots, include_workspace=True)

    def evaluate(
        self,
        tool_name: str,
        *,
        is_read_only: bool,
        file_path: str | None = None,
        command: str | None = None,
    ) -> PermissionDecision:
        if tool_name in self._settings.denied_tools:
            return PermissionDecision(allowed=False, reason=f"{tool_name} is explicitly denied")

        if tool_name in NETWORK_TOOLS and not self._sandbox.allow_network:
            return PermissionDecision(allowed=False, reason=f"{tool_name} is blocked because sandbox networking is disabled")

        if file_path:
            normalized = self._normalize_file_path(file_path)
            if normalized is not None:
                if not self._is_under_any_root(normalized, self._readable_roots):
                    return PermissionDecision(allowed=False, reason=f"Path {normalized} is outside the readable sandbox roots")
                if not is_read_only and not self._is_under_any_root(normalized, self._writable_roots):
                    return PermissionDecision(
                        allowed=False,
                        reason=f"Path {normalized} is outside the writable sandbox roots",
                    )
            for rule in self._settings.path_rules:
                if fnmatch.fnmatch(file_path, rule.pattern) and not rule.allow:
                    return PermissionDecision(
                        allowed=False,
                        reason=f"Path {file_path} matches deny rule: {rule.pattern}",
                    )

        if command:
            for pattern in self._settings.denied_commands:
                if fnmatch.fnmatch(command, pattern):
                    return PermissionDecision(
                        allowed=False,
                        reason=f"Command matches deny pattern: {pattern}",
                    )
            if tool_name == "bash" and self._sandbox.mode == "read-only":
                return PermissionDecision(allowed=False, reason="Read-only sandbox blocks bash execution")
            if tool_name == "bash" and self._sandbox.block_bash_by_default:
                return PermissionDecision(
                    allowed=False,
                    requires_confirmation=True,
                    reason="Sandbox policy requires approval before running bash commands",
                )

        if tool_name in self._settings.allowed_tools:
            return PermissionDecision(allowed=True, reason=f"{tool_name} is explicitly allowed")

        mode = self._settings.mode.lower()
        sandbox_mode = self._sandbox.mode.lower()
        if mode == "full-auto":
            if sandbox_mode == "read-only" and not is_read_only:
                return PermissionDecision(allowed=False, reason="Read-only sandbox blocks mutating tools")
            return PermissionDecision(allowed=True, reason="Full-auto mode allows the action inside sandbox bounds")

        if is_read_only:
            return PermissionDecision(allowed=True, reason="Read-only actions are allowed")

        if sandbox_mode == "read-only":
            return PermissionDecision(allowed=False, reason="Read-only sandbox blocks mutating tools")

        if mode == "plan":
            return PermissionDecision(
                allowed=False,
                reason="Plan mode blocks mutating tools until execution mode resumes",
            )

        return PermissionDecision(
            allowed=False,
            requires_confirmation=True,
            reason="Mutating tools require approval in default mode",
        )

    def _resolve_roots(self, configured_roots: list[str], *, include_workspace: bool) -> list[Path]:
        roots: list[Path] = []
        if include_workspace and self._workspace is not None:
            roots.append(self._workspace)
        for raw in configured_roots:
            path = Path(raw)
            if not path.is_absolute():
                if self._workspace is not None:
                    path = (self._workspace / path).resolve()
                else:
                    path = path.resolve()
            else:
                path = path.resolve()
            roots.append(path)
        deduped: list[Path] = []
        seen: set[str] = set()
        for path in roots:
            key = str(path)
            if key not in seen:
                deduped.append(path)
                seen.add(key)
        return deduped

    def _normalize_file_path(self, raw: str) -> Path | None:
        if not raw.strip():
            return None
        path = Path(raw)
        if not path.is_absolute():
            if self._workspace is None:
                return path.resolve()
            path = (self._workspace / path).resolve()
        else:
            path = path.resolve()
        return path

    def _is_under_any_root(self, path: Path, roots: list[Path]) -> bool:
        if not roots:
            return True
        for root in roots:
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue
        return False
