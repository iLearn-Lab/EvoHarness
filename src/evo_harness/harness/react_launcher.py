from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

from evo_harness.harness.console import enable_utf8_console


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def get_frontend_dir() -> Path:
    return _repo_root() / "frontend" / "terminal"


def _resolve_npm() -> str:
    return shutil.which("npm") or "npm"


def _resolve_node() -> str:
    return shutil.which("node") or "node"


def _tsx_cli(frontend_dir: Path) -> Path:
    candidate = frontend_dir / "node_modules" / "tsx" / "dist" / "cli.mjs"
    if not candidate.exists():
        raise RuntimeError(f"tsx CLI is missing: {candidate}")
    return candidate


def build_backend_command(
    *,
    workspace: str,
    settings_path: str | None = None,
    provider_script: str | None = None,
    resume: str | None = None,
) -> list[str]:
    command = [sys.executable, "-m", "evo_harness", "--backend-only", "--workspace", workspace]
    if settings_path:
        command.extend(["--settings", settings_path])
    if provider_script:
        command.extend(["--provider-script", provider_script])
    if resume:
        command.extend(["--resume", resume])
    return command


async def launch_react_tui(
    *,
    workspace: str,
    settings_path: str | None = None,
    provider_script: str | None = None,
    resume: str | None = None,
    initial_prompt: str | None = None,
) -> int:
    enable_utf8_console()
    frontend_dir = get_frontend_dir()
    package_json = frontend_dir / "package.json"
    if not package_json.exists():
        raise RuntimeError(f"React terminal frontend is missing: {package_json}")

    npm = _resolve_npm()
    if not (frontend_dir / "node_modules").exists():
        install = await asyncio.create_subprocess_exec(
            npm,
            "install",
            "--no-fund",
            "--no-audit",
            cwd=str(frontend_dir),
        )
        if await install.wait() != 0:
            raise RuntimeError("Failed to install React terminal frontend dependencies")

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUTF8", "1")
    env["EVO_HARNESS_FRONTEND_CONFIG"] = json.dumps(
        {
            "backend_command": build_backend_command(
                workspace=workspace,
                settings_path=settings_path,
                provider_script=provider_script,
                resume=resume,
            ),
            "initial_prompt": initial_prompt,
        }
    )
    node = _resolve_node()
    tsx_cli = _tsx_cli(frontend_dir)
    process = await asyncio.create_subprocess_exec(
        node,
        str(tsx_cli),
        "src/index.tsx",
        cwd=str(frontend_dir),
        env=env,
    )
    return await process.wait()


__all__ = ["get_frontend_dir", "build_backend_command", "launch_react_tui"]
