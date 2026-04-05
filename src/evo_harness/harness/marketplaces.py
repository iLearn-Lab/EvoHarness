from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from evo_harness.harness.settings import HarnessSettings


@dataclass(slots=True)
class MarketplacePlugin:
    name: str
    description: str
    source: str
    category: str = ""
    version: str = ""
    author: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MarketplaceDefinition:
    name: str
    source: dict[str, Any]
    path: str
    plugins: list[MarketplacePlugin]
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "path": self.path,
            "description": self.description,
            "plugins": [plugin.to_dict() for plugin in self.plugins],
        }


def load_marketplaces(workspace: str | Path, settings: HarnessSettings) -> list[MarketplaceDefinition]:
    root = Path(workspace).resolve()
    marketplaces: list[MarketplaceDefinition] = []
    default_sources = [
        {"name": "workspace-marketplace", "path": str(root / ".evo-harness" / "marketplace.json")},
        {"name": "claude-plugin-marketplace", "path": str(root / ".claude-plugin" / "marketplace.json")},
    ]
    all_sources = [*default_sources, *settings.managed.extra_known_marketplaces]
    for source in all_sources:
        marketplace = _load_marketplace_from_source(source, workspace_root=root)
        if marketplace is None:
            continue
        if _marketplace_allowed(marketplace, settings):
            marketplaces.append(marketplace)
    return marketplaces


def install_marketplace_plugin(
    workspace: str | Path,
    *,
    marketplace_name: str,
    plugin_name: str,
    settings: HarnessSettings,
) -> Path:
    root = Path(workspace).resolve()
    marketplaces = load_marketplaces(root, settings)
    marketplace = next((item for item in marketplaces if item.name == marketplace_name), None)
    if marketplace is None:
        raise ValueError(f"Marketplace not found: {marketplace_name}")
    plugin = next((item for item in marketplace.plugins if item.name == plugin_name), None)
    if plugin is None:
        raise ValueError(f"Plugin not found in marketplace: {plugin_name}")
    marketplace_path = Path(marketplace.path).resolve()
    source_root = marketplace_path.parent
    plugin_source = (source_root / plugin.source).resolve()
    if not plugin_source.exists():
        raise FileNotFoundError(f"Plugin source not found: {plugin_source}")
    target_root = root / "plugins" / plugin.name
    if target_root.exists():
        shutil.rmtree(target_root)
    shutil.copytree(plugin_source, target_root)
    return target_root


def _load_marketplace_from_source(source: dict[str, Any], *, workspace_root: Path) -> MarketplaceDefinition | None:
    path_value = source.get("path")
    if not path_value:
        return None
    path = Path(str(path_value))
    if not path.is_absolute():
        path = (workspace_root / path).resolve()
    else:
        path = path.resolve()
    if path.is_dir():
        path = path / "marketplace.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return MarketplaceDefinition(
        name=str(source.get("name", raw.get("name", path.stem))),
        source=source,
        path=str(path),
        description=str(raw.get("description", "")),
        plugins=[
            MarketplacePlugin(
                name=str(item["name"]),
                description=str(item.get("description", "")),
                source=str(item.get("source", "")),
                category=str(item.get("category", "")),
                version=str(item.get("version", "")),
                author=item.get("author"),
            )
            for item in raw.get("plugins", [])
        ],
    )


def _marketplace_allowed(marketplace: MarketplaceDefinition, settings: HarnessSettings) -> bool:
    strict = settings.managed.strict_known_marketplaces
    if not strict:
        return True
    marketplace_path = marketplace.source.get("path")
    for candidate in strict:
        if candidate.get("path") and str(candidate["path"]) == str(marketplace_path):
            return True
    return False
