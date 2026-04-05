from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from evo_harness.harness.frontmatter import split_list_like
from evo_harness.harness.settings import HarnessSettings, get_default_settings_path, load_settings


@dataclass(slots=True)
class PluginManifest:
    name: str
    version: str = "0.0.0"
    description: str = ""
    enabled_by_default: bool = True
    skills_dir: str = "skills"
    hooks_file: str = "hooks.json"
    hooks_dir: str = "hooks"
    commands_dir: str = "commands"
    agents_dir: str = "agents"
    mcp_file: str = ".mcp.json"
    settings_namespace: str | None = None
    default_settings: dict[str, Any] = field(default_factory=dict)
    required_plugins: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    author: dict[str, Any] | None = None
    homepage: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LoadedPlugin:
    manifest: PluginManifest
    path: str
    source: str
    effective_settings: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "path": self.path,
            "source": self.source,
            "effective_settings": self.effective_settings,
            "warnings": self.warnings,
        }


def get_user_plugins_dir() -> Path:
    path = get_default_settings_path().parent / "plugins"
    path.mkdir(parents=True, exist_ok=True)
    return path


def discover_plugin_paths(workspace: str | Path) -> list[tuple[Path, str]]:
    root = Path(workspace).resolve()
    candidates: list[tuple[Path, str]] = []
    plugin_roots = [
        (get_user_plugins_dir(), "user"),
        (root / "plugins", "workspace"),
        (root / ".evo-harness" / "plugins", "evo-harness"),
        (root / ".openharness" / "plugins", "openharness"),
    ]
    for plugin_root, source in plugin_roots:
        if not plugin_root.exists():
            continue
        for path in sorted(plugin_root.iterdir()):
            if path.is_dir() and _find_manifest(path) is not None:
                candidates.append((path, source))
    return candidates


def load_workspace_plugins(workspace: str | Path, settings: HarnessSettings | None = None) -> list[LoadedPlugin]:
    settings = settings or load_settings(workspace=workspace)
    discovered = discover_plugin_paths(workspace)
    plugins: list[LoadedPlugin] = []
    loaded_names: set[str] = set()
    for path, source in discovered:
        manifest_path = _find_manifest(path)
        if manifest_path is None:
            continue
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        manifest = PluginManifest(
            name=str(raw["name"]),
            version=str(raw.get("version", "0.0.0")),
            description=str(raw.get("description", "")),
            enabled_by_default=bool(raw.get("enabled_by_default", True)),
            skills_dir=str(raw.get("skills_dir", "skills")),
            hooks_file=str(raw.get("hooks_file", "hooks.json")),
            hooks_dir=str(raw.get("hooks_dir", "hooks")),
            commands_dir=str(raw.get("commands_dir", "commands")),
            agents_dir=str(raw.get("agents_dir", "agents")),
            mcp_file=str(raw.get("mcp_file", ".mcp.json")),
            settings_namespace=raw.get("settings_namespace"),
            default_settings=dict(raw.get("default_settings", {})),
            required_plugins=split_list_like(raw.get("required_plugins")) or [],
            tags=split_list_like(raw.get("tags")) or [],
            author=raw.get("author"),
            homepage=raw.get("homepage"),
        )
        if manifest.name in loaded_names:
            continue
        enabled = settings.enabled_plugins.get(manifest.name, manifest.enabled_by_default)
        if not enabled:
            continue
        effective_settings = _deep_merge(
            dict(manifest.default_settings),
            dict(settings.plugin_settings.get(manifest.name, {})),
        )
        warnings = [
            f"Missing plugin dependency: {required}"
            for required in manifest.required_plugins
            if required not in settings.enabled_plugins and not _plugin_exists(discovered, required)
        ]
        plugins.append(
            LoadedPlugin(
                manifest=manifest,
                path=str(path),
                source=source,
                effective_settings=effective_settings,
                warnings=warnings,
            )
        )
        loaded_names.add(manifest.name)
    return plugins


def _plugin_exists(discovered: list[tuple[Path, str]], name: str) -> bool:
    for path, _source in discovered:
        manifest_path = _find_manifest(path)
        if manifest_path is None:
            continue
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if str(raw.get("name", path.name)) == name:
            return True
    return False


def _find_manifest(plugin_dir: Path) -> Path | None:
    for candidate in (
        plugin_dir / "plugin.json",
        plugin_dir / ".claude-plugin" / "plugin.json",
        plugin_dir / ".openharness-plugin" / "plugin.json",
        plugin_dir / ".evo-harness-plugin" / "plugin.json",
    ):
        if candidate.exists():
            return candidate
    return None


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
