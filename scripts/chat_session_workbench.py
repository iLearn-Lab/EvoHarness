from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from evo_harness.harness.settings import load_settings, save_settings
from evo_harness.harness.console import enable_utf8_console
from evo_harness.harness.provider import detect_provider_profile


def _copy_workspace(source: Path, target: Path) -> Path:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return target


def _prepare_settings(
    workspace: Path,
    *,
    provider: str,
    model: str,
    api_key_env: str,
    base_url: str | None,
) -> Path:
    settings = load_settings(workspace=workspace)
    profile = detect_provider_profile(profile=provider, model=model, base_url=base_url)
    settings.model = model
    settings.provider.provider = profile.name
    settings.provider.profile = profile.name
    settings.provider.api_key = None
    settings.provider.api_key_env = api_key_env
    settings.provider.api_format = profile.api_format
    settings.provider.auth_scheme = profile.auth_scheme
    settings.provider.base_url = base_url or profile.default_base_url
    settings.permission.mode = "default"
    settings.runtime.auto_self_evolution = True
    settings.runtime.auto_self_evolution_mode = "candidate"
    path = workspace / ".evo-harness" / "settings.chat-workbench.json"
    return save_settings(settings, path)


class ChatHarnessClient:
    def __init__(self, *, workspace: Path, settings_path: Path) -> None:
        env = os.environ.copy()
        current_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(SRC_ROOT) + (os.pathsep + current_pythonpath if current_pythonpath else "")
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "evo_harness",
                "--backend-only",
                "--workspace",
                str(workspace),
                "--settings",
                str(settings_path),
            ],
            cwd=str(REPO_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        assert self.process.stderr is not None
        self.stdout_queue: queue.Queue[str] = queue.Queue()
        self.stderr_queue: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._pump, args=(self.process.stdout, self.stdout_queue), daemon=True).start()
        threading.Thread(target=self._pump, args=(self.process.stderr, self.stderr_queue), daemon=True).start()
        self.events: list[dict[str, object]] = []

    @staticmethod
    def _pump(stream, target: queue.Queue[str]) -> None:
        for line in iter(stream.readline, ""):
            target.put(line.rstrip("\n"))

    def _read_event(self, timeout_s: float = 0.5) -> dict[str, object] | None:
        try:
            line = self.stdout_queue.get(timeout=timeout_s)
        except queue.Empty:
            return None
        if not line.startswith("EVOJSON:"):
            self.events.append({"type": "log", "line": line})
            return {"type": "log", "line": line}
        payload = json.loads(line[len("EVOJSON:") :])
        self.events.append(payload)
        return payload

    def wait_ready(self, timeout_s: float = 10.0) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            event = self._read_event()
            if event and event.get("type") == "ready":
                return
        raise TimeoutError("Backend did not reach ready state")

    def send_line(self, line: str, *, approval_policy: dict[str, bool] | None = None, timeout_s: float = 150.0) -> list[dict[str, object]]:
        approval_policy = approval_policy or {}
        self.process.stdin.write(json.dumps({"type": "submit_line", "line": line}, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        collected: list[dict[str, object]] = []
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            event = self._read_event()
            if event is None:
                continue
            collected.append(event)
            event_type = str(event.get("type", ""))
            if event_type == "modal_request":
                modal = dict(event.get("modal", {}) or {})
                kind = str(modal.get("kind", ""))
                if kind == "permission":
                    tool_name = str(modal.get("tool_name", ""))
                    allowed = approval_policy.get(tool_name, True)
                    response = {
                        "type": "permission_response",
                        "request_id": str(modal.get("request_id", "")),
                        "allowed": allowed,
                    }
                    self.process.stdin.write(json.dumps(response) + "\n")
                    self.process.stdin.flush()
                elif kind == "question":
                    response = {
                        "type": "question_response",
                        "request_id": str(modal.get("request_id", "")),
                        "answer": "",
                    }
                    self.process.stdin.write(json.dumps(response, ensure_ascii=False) + "\n")
                    self.process.stdin.flush()
            if event_type == "line_complete":
                return collected
        raise TimeoutError(f"Timed out waiting for line completion: {line}")

    def shutdown(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.stdin.write(json.dumps({"type": "shutdown"}) + "\n")
        self.process.stdin.flush()
        self.process.wait(timeout=5.0)
        self.process.stdin.close()
        self.process.stdout.close()
        self.process.stderr.close()


def _event_summary(events: list[dict[str, object]]) -> dict[str, object]:
    tool_starts = [event.get("tool_name") for event in events if event.get("type") == "tool_started"]
    assistant_messages = [str(event.get("message", "")) for event in events if event.get("type") == "assistant_complete"]
    system_messages = [
        str(dict(event.get("item", {}) or {}).get("text", ""))
        for event in events
        if event.get("type") == "transcript_item"
        and str(dict(event.get("item", {}) or {}).get("role", "")) in {"system", "assistant"}
    ]
    modal_kinds = [dict(event.get("modal", {}) or {}).get("kind") for event in events if event.get("type") == "modal_request"]
    return {
        "tool_calls": tool_starts,
        "assistant_preview": (
            assistant_messages[-1][:280]
            if assistant_messages
            else (system_messages[-1][:280] if system_messages else "")
        ),
        "modal_kinds": modal_kinds,
    }


def _last_text(events: list[dict[str, object]]) -> str:
    for event in reversed(events):
        if event.get("type") == "assistant_complete":
            return str(event.get("message", ""))
        if event.get("type") == "transcript_item":
            item = dict(event.get("item", {}) or {})
            if str(item.get("text", "")):
                return str(item.get("text", ""))
    return ""


def main() -> None:
    enable_utf8_console()
    parser = argparse.ArgumentParser(description="Exercise Evo Harness through the chat/backend protocol and simulate user decisions.")
    parser.add_argument("--provider", required=True, help="Provider/profile name.")
    parser.add_argument("--model", required=True, help="Model name.")
    parser.add_argument("--api-key-env", required=True, help="Environment variable containing the API key.")
    parser.add_argument("--base-url", help="Optional base URL override.")
    parser.add_argument("--workspace-out", help="Optional persistent output workspace path.")
    parser.add_argument("--source-workspace", default=str(REPO_ROOT), help="Workspace template copied before chat testing.")
    args = parser.parse_args()

    if not os.environ.get(args.api_key_env):
        raise SystemExit(f"Missing API key environment variable: {args.api_key_env}")

    workspace_target = Path(args.workspace_out).resolve() if args.workspace_out else None
    tempdir: tempfile.TemporaryDirectory[str] | None = None
    if workspace_target is None:
        tempdir = tempfile.TemporaryDirectory(prefix="evo-chat-workbench-")
        workspace_target = Path(tempdir.name) / "workspace"

    try:
        workspace = _copy_workspace(Path(args.source_workspace).resolve(), workspace_target)
        settings_path = _prepare_settings(
            workspace,
            provider=args.provider,
            model=args.model,
            api_key_env=args.api_key_env,
            base_url=args.base_url,
        )
        client = ChatHarnessClient(workspace=workspace, settings_path=settings_path)
        try:
            client.wait_ready()
            task_create_events = client.send_line(f"/tasks run \"{sys.executable}\" -c \"print('chat task ok')\"")
            transcript = {
                "status": _event_summary(client.send_line("/status")),
                "clear_after_status": _event_summary(client.send_line("/clear")),
                "ecosystem": _event_summary(
                    client.send_line(
                        "请先自己检查这个工作区里有哪些技能、命令、agent、plugin 和 MCP 资源；如果发现有相关技能或 MCP 能力，请主动调用它们，再用中文总结这个 harness 现在能做什么。"
                    )
                ),
                "clear_after_ecosystem": _event_summary(client.send_line("/clear")),
                "subagent": _event_summary(client.send_line("/agents run explore :: Inspect the workspace ecosystem and summarize the codebase structure and available workflow assets.")),
                "clear_after_subagent": _event_summary(client.send_line("/clear")),
                "permissions_default": _event_summary(client.send_line("/permissions default")),
                "task_create": _event_summary(task_create_events),
                "clear_after_task": _event_summary(client.send_line("/clear")),
                "approval_flow": _event_summary(
                    client.send_line(
                        "Please create a file named chat-approved-note.txt with the content approved from chat and then confirm where you wrote it.",
                        approval_policy={"write_file": True},
                    )
                ),
                "memory": _event_summary(client.send_line("/memory add Chat Approval :: chat approval flow tested")),
                "evolution_plan": _event_summary(client.send_line("/evolve plan")),
                "evolution_candidate": _event_summary(client.send_line("/evolve candidate")),
            }
            task_create_text = _last_text(task_create_events)
            try:
                task_payload = json.loads(task_create_text)
                task_id = str(task_payload["id"])
            except Exception:
                task_id = ""
            transcript["task_create"] = {
                **transcript["task_create"],
                "assistant_preview": task_create_text[:280],
            }
            if task_id:
                transcript["task_wait"] = _event_summary(client.send_line(f"/tasks wait {task_id}"))
                transcript["task_output"] = _event_summary(client.send_line(f"/tasks output {task_id}"))
            print(json.dumps({"workspace": str(workspace), "transcript": transcript}, indent=2, ensure_ascii=False))
        finally:
            client.shutdown()
    finally:
        if tempdir is not None:
            tempdir.cleanup()


if __name__ == "__main__":
    main()
