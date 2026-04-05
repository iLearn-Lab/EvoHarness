from __future__ import annotations

import base64
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal
from uuid import uuid4


TaskType = Literal["local_bash", "local_agent", "subagent"]
TaskStatus = Literal["pending", "running", "completed", "failed", "killed"]


@dataclass(slots=True)
class TaskRecord:
    id: str
    type: TaskType
    status: TaskStatus
    description: str
    cwd: str
    output_file: str
    exit_file: str
    command: str
    pid: int | None = None
    prompt: str | None = None
    created_at: float = 0.0
    started_at: float | None = None
    ended_at: float | None = None
    return_code: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "TaskRecord":
        return cls(
            id=str(payload["id"]),
            type=str(payload["type"]),
            status=str(payload["status"]),
            description=str(payload["description"]),
            cwd=str(payload["cwd"]),
            output_file=str(payload["output_file"]),
            exit_file=str(payload["exit_file"]),
            command=str(payload["command"]),
            pid=payload.get("pid"),
            prompt=payload.get("prompt"),
            created_at=float(payload.get("created_at", 0.0)),
            started_at=payload.get("started_at"),
            ended_at=payload.get("ended_at"),
            return_code=payload.get("return_code"),
            metadata=dict(payload.get("metadata", {})),
        )


class TaskManager:
    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.root = self.workspace / ".evo-harness" / "tasks"
        self.records_dir = self.root / "records"
        self.logs_dir = self.root / "logs"
        self.exits_dir = self.root / "exits"
        self.commands_dir = self.root / "commands"
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.exits_dir.mkdir(parents=True, exist_ok=True)
        self.commands_dir.mkdir(parents=True, exist_ok=True)

    def create_shell_task(
        self,
        *,
        command: str,
        description: str,
        cwd: str | Path | None = None,
        task_type: TaskType = "local_bash",
        prompt: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> TaskRecord:
        task_id = _task_id(task_type)
        cwd_path = Path(cwd or self.workspace).resolve()
        log_file = self.logs_dir / f"{task_id}.log"
        exit_file = self.exits_dir / f"{task_id}.exit"
        record = TaskRecord(
            id=task_id,
            type=task_type,
            status="running",
            description=description,
            cwd=str(cwd_path),
            output_file=str(log_file),
            exit_file=str(exit_file),
            command=command,
            prompt=prompt,
            created_at=time.time(),
            started_at=time.time(),
            metadata=metadata or {},
        )
        pid = self._spawn_background_process(record)
        record.pid = pid
        self._write_record(record)
        return record

    def create_agent_task(
        self,
        *,
        agent_name: str,
        task: str,
        provider_script: str | Path,
        description: str | None = None,
        max_turns: int = 8,
        settings_path: str | Path | None = None,
    ) -> TaskRecord:
        command_parts = [
            _quote(sys.executable),
            "-m",
            "evo_harness",
            "run-agent",
            "--workspace",
            _quote(str(self.workspace)),
            "--name",
            _quote(agent_name),
            "--task",
            _quote(task),
            "--provider-script",
            _quote(str(Path(provider_script).resolve())),
            "--max-turns",
            str(max_turns),
        ]
        if settings_path is not None:
            command_parts.extend(["--settings", _quote(str(Path(settings_path).resolve()))])
        command = " ".join(command_parts)
        return self.create_shell_task(
            command=command,
            description=description or f"Run agent {agent_name}",
            task_type="subagent",
            prompt=task,
            metadata={"agent_name": agent_name},
        )

    def get_task(self, task_id: str) -> TaskRecord | None:
        path = self.records_dir / f"{task_id}.json"
        if not path.exists():
            return None
        record = TaskRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        return self.refresh_task(record)

    def list_tasks(self, *, status: TaskStatus | None = None) -> list[TaskRecord]:
        records: list[TaskRecord] = []
        for path in sorted(self.records_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            record = TaskRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
            record = self.refresh_task(record)
            if status is None or record.status == status:
                records.append(record)
        return records

    def refresh_task(self, record: TaskRecord) -> TaskRecord:
        exit_file = Path(record.exit_file)
        if exit_file.exists() and record.status == "running":
            try:
                return_code = int(exit_file.read_text(encoding="utf-8").strip())
            except ValueError:
                return_code = 1
            record.return_code = return_code
            record.status = "completed" if return_code == 0 else "failed"
            record.ended_at = record.ended_at or time.time()
            self._write_record(record)
            return record
        return record

    def read_task_output(self, task_id: str, *, max_bytes: int = 12000) -> str:
        record = self.get_task(task_id)
        if record is None:
            raise ValueError(f"No task found with ID: {task_id}")
        content = Path(record.output_file).read_text(encoding="utf-8", errors="replace")
        if len(content) > max_bytes:
            return content[-max_bytes:]
        return content

    def stop_task(self, task_id: str) -> TaskRecord:
        record = self.get_task(task_id)
        if record is None:
            raise ValueError(f"No task found with ID: {task_id}")
        if record.pid is not None and _process_exists(record.pid):
            _terminate_process(record.pid)
        record.status = "killed"
        record.ended_at = time.time()
        self._write_record(record)
        return record

    def wait_task(self, task_id: str, *, timeout_s: float = 30.0, poll_interval_s: float = 0.2) -> TaskRecord:
        start = time.time()
        while True:
            record = self.get_task(task_id)
            if record is None:
                raise ValueError(f"No task found with ID: {task_id}")
            if record.status in {"completed", "failed", "killed"}:
                return record
            if time.time() - start >= timeout_s:
                return record
            time.sleep(poll_interval_s)

    def prune_tasks(self, *, keep_last: int = 50) -> int:
        records = self.list_tasks()
        removed = 0
        for record in records[keep_last:]:
            for path_str in (record.output_file, record.exit_file, self.records_dir / f"{record.id}.json"):
                path = Path(path_str)
                if path.exists():
                    try:
                        path.unlink()
                    except OSError:
                        pass
            removed += 1
        return removed

    def _spawn_background_process(self, record: TaskRecord) -> int:
        log_file = Path(record.output_file)
        exit_file = Path(record.exit_file)
        src_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        current_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(src_root) + (os.pathsep + current_pythonpath if current_pythonpath else "")
        command_b64 = base64.b64encode(record.command.encode("utf-8")).decode("ascii")
        runner_cmd = [
            sys.executable,
            "-m",
            "evo_harness.harness.task_runner",
            "--command-b64",
            command_b64,
            "--cwd",
            record.cwd,
            "--log-file",
            str(log_file),
            "--exit-file",
            str(exit_file),
        ]
        popen_kwargs: dict[str, object] = {
            "cwd": record.cwd,
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            creationflags = 0
            for flag_name in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS", "CREATE_NO_WINDOW"):
                creationflags |= int(getattr(subprocess, flag_name, 0) or 0)
            if creationflags:
                popen_kwargs["creationflags"] = creationflags
        else:
            popen_kwargs["start_new_session"] = True
        process = subprocess.Popen(runner_cmd, **popen_kwargs)
        pid = int(process.pid)
        # Detach the launcher handle; the task lifecycle is tracked via pid/exit files instead.
        process._child_created = False  # type: ignore[attr-defined]
        return pid

    def _write_record(self, record: TaskRecord) -> None:
        path = self.records_dir / f"{record.id}.json"
        path.write_text(json.dumps(record.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def get_task_manager(workspace: str | Path) -> TaskManager:
    return TaskManager(workspace)


def _task_id(task_type: TaskType) -> str:
    prefixes = {"local_bash": "b", "local_agent": "a", "subagent": "t"}
    return f"{prefixes[task_type]}{uuid4().hex[:8]}"


def _quote(value: str) -> str:
    if os.name == "nt":
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    import shlex

    return shlex.quote(value)


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return str(pid) in completed.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _terminate_process(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True)
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
