from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass(slots=True)
class EnvironmentInfo:
    os_name: str
    os_version: str
    platform_machine: str
    shell: str
    cwd: str
    date: str
    python_version: str
    is_git_repo: bool
    git_branch: str | None = None

    def to_dict(self) -> dict[str, str | bool | None]:
        return asdict(self)


def get_environment_info(cwd: str | Path | None = None) -> EnvironmentInfo:
    resolved = Path(cwd or os.getcwd()).resolve()
    shell = os.environ.get("SHELL") or os.environ.get("COMSPEC") or "unknown"
    is_git_repo, branch = _get_git_status(resolved)
    return EnvironmentInfo(
        os_name=platform.system(),
        os_version=platform.version(),
        platform_machine=platform.machine(),
        shell=shell,
        cwd=str(resolved),
        date=datetime.now().isoformat(timespec="seconds"),
        python_version=sys.version.split()[0],
        is_git_repo=is_git_repo,
        git_branch=branch,
    )


def _get_git_status(cwd: Path) -> tuple[bool, str | None]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or result.stdout.strip().lower() != "true":
            return False, None
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
        )
        return True, branch.stdout.strip() or None
    except OSError:
        return False, None

