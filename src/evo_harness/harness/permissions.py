from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from evo_harness.harness.settings import PermissionSettings, SandboxSettings


NETWORK_TOOLS = {"download_file", "web_fetch", "web_search", "mcp_call_tool", "mcp_read_resource", "mcp_get_prompt"}
SAFE_GIT_SUBCOMMANDS = {
    "status",
    "diff",
    "log",
    "show",
    "branch",
    "rev-parse",
    "grep",
    "ls-files",
    "remote",
    "tag",
    "blame",
    "symbolic-ref",
}
SAFE_NPM_SUBCOMMANDS = {"test", "run", "exec", "list", "ls"}
SAFE_PNPM_SUBCOMMANDS = {"test", "run", "exec", "list", "ls"}
SAFE_YARN_SUBCOMMANDS = {"test", "run", "list", "why"}
SAFE_CARGO_SUBCOMMANDS = {"test", "check", "fmt", "clippy", "metadata"}
SAFE_DOTNET_SUBCOMMANDS = {"test", "--info", "--list-sdks", "--version"}
SAFE_GO_SUBCOMMANDS = {"test", "env", "version", "list"}
SAFE_MVN_SUBCOMMANDS = {"test", "-v", "--version"}
SAFE_GRADLE_SUBCOMMANDS = {"test", "tasks", "properties", "--version", "-v"}
SAFE_SHELL_PREFIXES = (
    "get-",
    "select-string",
    "where-object",
    "measure-object",
    "sort-object",
    "group-object",
    "format-table",
    "format-list",
    "out-string",
    "get-command",
    "get-location",
    "set-location",
    "push-location",
    "pop-location",
    "pwd",
    "ls",
    "dir",
    "cat",
    "type",
    "rg",
    "findstr",
    "echo",
    "cls",
    "clear",
    "whoami",
    "hostname",
    "uname",
    "env",
)
MUTATING_SHELL_MARKERS = (
    ">>",
    ">",
    "set-content",
    "add-content",
    "out-file",
    "new-item",
    "ni ",
    "mkdir ",
    "md ",
    "remove-item",
    "del ",
    "erase ",
    "copy-item",
    "move-item",
    "rename-item",
    "clear-content",
    "git add",
    "git commit",
    "git apply",
    "git am",
    "git stash",
    "git checkout",
    "git switch",
    "git restore",
    "git clean",
    "git reset",
    "git rebase",
    "git merge",
    "npm install",
    "npm update",
    "npm audit fix",
    "pnpm add",
    "pnpm install",
    "pnpm update",
    "yarn add",
    "yarn install",
    "pip install",
    "python -m pip install",
    "uv pip install",
    "uv sync",
    "poetry add",
    "poetry install",
    "cargo add",
    "cargo install",
    "go get",
    "go mod tidy",
    "dotnet add",
    "dotnet restore",
)


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

        mode = normalize_permission_mode(self._settings.mode)
        sandbox_mode = self._sandbox.mode.lower()
        if mode == "full-access":
            if sandbox_mode == "read-only" and not is_read_only:
                return PermissionDecision(allowed=False, reason="Read-only sandbox blocks mutating tools")
            return PermissionDecision(allowed=True, reason="Full-access mode allows the action inside sandbox bounds")

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


def normalize_permission_mode(mode: str) -> str:
    lowered = str(mode or "default").strip().lower().replace("_", "-")
    aliases = {
        "auto": "full-access",
        "full-auto": "full-access",
        "fullaccess": "full-access",
        "default": "default",
        "plan": "plan",
        "full-access": "full-access",
    }
    return aliases.get(lowered, lowered or "default")


def is_safe_shell_command(command: str) -> bool:
    normalized = _normalize_shell_command(command)
    if not normalized:
        return False
    if _contains_mutating_shell_marker(normalized):
        return False
    if normalized.startswith(SAFE_SHELL_PREFIXES):
        return True
    if _is_safe_git_command(normalized):
        return True
    if _is_safe_python_command(normalized):
        return True
    if _is_safe_node_command(normalized):
        return True
    if _is_safe_toolchain_command(normalized):
        return True
    return False


def _normalize_shell_command(command: str) -> str:
    return " ".join(str(command or "").strip().lower().split())


def _contains_mutating_shell_marker(command: str) -> bool:
    for marker in MUTATING_SHELL_MARKERS:
        if marker == ">":
            if " > " in command or command.endswith(">") or command.startswith(">"):
                return True
            continue
        if marker in command:
            return True
    return False


def _is_safe_git_command(command: str) -> bool:
    if not command.startswith("git "):
        return False
    parts = command.split()
    return len(parts) >= 2 and parts[1] in SAFE_GIT_SUBCOMMANDS


def _is_safe_python_command(command: str) -> bool:
    if command in {"python", "python --version", "python -v", "python -vv"}:
        return True
    if command.startswith("python -m "):
        return command.startswith("python -m unittest") or command.startswith("python -m pytest")
    if command.startswith("pytest") or command.startswith("py.test"):
        return True
    if command.startswith("python -c "):
        return not any(
            marker in command
            for marker in (
                "write_text",
                "write_bytes",
                "unlink",
                "rmdir",
                "mkdir",
                "remove(",
                "replace(",
                "rename(",
                "shutil.",
                "subprocess.",
                "open(",
            )
        )
    return False


def _is_safe_node_command(command: str) -> bool:
    if command.startswith("npm "):
        return _is_safe_package_manager_command(command, "npm", SAFE_NPM_SUBCOMMANDS)
    if command.startswith("pnpm "):
        return _is_safe_package_manager_command(command, "pnpm", SAFE_PNPM_SUBCOMMANDS)
    if command.startswith("yarn "):
        return _is_safe_package_manager_command(command, "yarn", SAFE_YARN_SUBCOMMANDS)
    if command.startswith("tsc "):
        return "--noemit" in command
    if command.startswith("npx tsc ") or command.startswith("npm exec -- tsc "):
        return "--noemit" in command
    return False


def _is_safe_package_manager_command(command: str, prefix: str, safe_subcommands: set[str]) -> bool:
    parts = command.split()
    if len(parts) < 2 or parts[0] != prefix:
        return False
    if parts[1] not in safe_subcommands:
        return False
    if parts[1] in {"run", "exec"}:
        return "test" in parts or ("tsc" in parts and "--noemit" in command)
    return True


def _is_safe_toolchain_command(command: str) -> bool:
    parts = command.split()
    if not parts:
        return False
    head = parts[0]
    if head == "cargo":
        return len(parts) >= 2 and parts[1] in SAFE_CARGO_SUBCOMMANDS
    if head == "dotnet":
        return len(parts) >= 2 and parts[1] in SAFE_DOTNET_SUBCOMMANDS
    if head == "go":
        return len(parts) >= 2 and parts[1] in SAFE_GO_SUBCOMMANDS
    if head in {"mvn", "mvn.cmd"}:
        return len(parts) >= 2 and parts[1] in SAFE_MVN_SUBCOMMANDS
    if head in {"gradle", ".\\gradlew", "./gradlew"}:
        return len(parts) >= 2 and parts[1] in SAFE_GRADLE_SUBCOMMANDS
    return False
