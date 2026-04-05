from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from evo_harness.execution import ControlledEvolutionExecutor
from evo_harness.harness import (
    ConversationEngine,
    HarnessRuntime,
    build_live_provider,
    find_agent,
    run_subagent,
)
from evo_harness.harness.console import enable_utf8_console
from evo_harness.models import HarnessCapabilities


def _build_capabilities() -> HarnessCapabilities:
    return HarnessCapabilities(
        adapter_name="openharness",
        skill_upgrade=True,
        skill_validate=True,
        skill_rollback=True,
        memory_write=True,
        memory_archive=True,
        session_fork=True,
        replay_validation=True,
        regression_suite=True,
        artifact_access=True,
        execution_history=True,
        workspace_instructions=True,
    )


def _copy_workspace(source: Path, target: Path) -> Path:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return target


def _workspace_summary(runtime: HarnessRuntime) -> dict[str, object]:
    return {
        "workspace": str(runtime.workspace),
        "commands": len(runtime.list_commands()),
        "agents": len(runtime.list_agents()),
        "plugins": len(runtime.list_plugins()),
        "mcp_servers": len(runtime.list_mcp_servers()),
        "mcp_tools": len(runtime.list_mcp_tools()),
        "mcp_resources": len(runtime.list_mcp_resources()),
        "mcp_prompts": len(runtime.list_mcp_prompts()),
        "tools": len(runtime.list_tools()),
    }


def _ecosystem_checks(runtime: HarnessRuntime) -> dict[str, object]:
    skill_result = runtime.execute_tool("skill", {"name": "harness-ecosystem"})
    command_result = runtime.execute_tool(
        "render_command",
        {"name": "feature-dev", "arguments": "Smoke-test the live harness ecosystem."},
    )
    registry_result = runtime.execute_tool("list_registry", {"kind": "all"})
    return {
        "skill": {"is_error": skill_result.is_error, "preview": skill_result.output[:220]},
        "command": {"is_error": command_result.is_error, "preview": command_result.output[:220]},
        "registry": {"is_error": registry_result.is_error, "preview": registry_result.output[:260]},
    }


def _direct_tool_checks(runtime: HarnessRuntime) -> dict[str, object]:
    read_result = runtime.execute_tool("read_file", {"path": "CLAUDE.md"})
    large_fixture = runtime.workspace / "smoke-large.txt"
    large_fixture.write_text(
        "\n".join(f"line {index}: smoke segment with repeated keyword harness" for index in range(1, 241)) + "\n",
        encoding="utf-8",
    )
    segmented_read = runtime.execute_tool("read_file", {"path": "smoke-large.txt"})
    paged_search = runtime.execute_tool("grep", {"pattern": "harness", "glob": "smoke-large.txt", "limit": 5})
    first_write = runtime.execute_tool("write_file", {"path": "smoke-note.txt", "content": "hello workbench"})
    approval_id = (first_write.metadata or {}).get("approval_request_id")
    write_after_approval: dict[str, object]
    if approval_id:
        runtime.approval_manager.decide(str(approval_id), approved=True, note="live workbench auto-approval")
        second_write = runtime.execute_tool("write_file", {"path": "smoke-note.txt", "content": "hello workbench"})
        write_after_approval = {
            "is_error": second_write.is_error,
            "output": second_write.output,
            "exists": (runtime.workspace / "smoke-note.txt").exists(),
        }
    else:
        write_after_approval = {"skipped": True}
    return {
        "read_file": {
            "is_error": read_result.is_error,
            "output_preview": read_result.output[:160],
        },
        "segmented_read_file": {
            "is_error": segmented_read.is_error,
            "output_preview": segmented_read.output[:280],
            "metadata": segmented_read.metadata,
        },
        "paged_search": {
            "is_error": paged_search.is_error,
            "output_preview": paged_search.output[:280],
            "metadata": paged_search.metadata,
        },
        "write_file_initial": {
            "is_error": first_write.is_error,
            "output": first_write.output,
            "approval_request_id": approval_id,
        },
        "write_file_after_approval": write_after_approval,
    }


def _mcp_checks(runtime: HarnessRuntime) -> dict[str, object]:
    tool_result = runtime.execute_tool(
        "mcp_call_tool",
        {"server": "workspace-docs", "name": "search_docs", "arguments": {"query": "self-evolution"}},
    )
    resource_result = runtime.execute_tool(
        "mcp_read_resource",
        {"server": "workspace-docs", "uri": "docs://readme"},
    )
    prompt_result = runtime.execute_tool(
        "mcp_get_prompt",
        {"server": "workspace-docs", "name": "triage_workspace_gap", "arguments": {"gap": "skills not being used"}},
    )
    return {
        "tool": {"is_error": tool_result.is_error, "preview": tool_result.output[:240]},
        "resource": {"is_error": resource_result.is_error, "preview": resource_result.output[:240]},
        "prompt": {"is_error": prompt_result.is_error, "preview": prompt_result.output[:240]},
    }


def _live_query_check(runtime: HarnessRuntime, *, provider, prompt: str, max_turns: int) -> dict[str, object]:
    engine = ConversationEngine(runtime)
    result = engine.submit(prompt=prompt, provider=provider, max_turns=max_turns)
    assistant_messages = [message for message in result.messages if message.get("role") == "assistant"]
    tool_results = [event for event in result.events if event.get("kind") == "tool_result"]
    return {
        "provider_name": result.provider_name,
        "stop_reason": result.stop_reason,
        "turn_count": result.turn_count,
        "usage": result.usage,
        "tool_result_count": len(tool_results),
        "assistant_preview": assistant_messages[-1]["text"][:300] if assistant_messages else "",
        "session_path": result.session_path,
    }


def _subagent_check(runtime: HarnessRuntime, *, provider) -> dict[str, object]:
    agent = find_agent(runtime.workspace, "explore")
    if agent is None:
        return {"available": False}
    result = run_subagent(
        runtime,
        agent=agent,
        task="Inspect the workspace ecosystem and summarize the available commands, skills, plugins, and MCP assets.",
        provider=provider,
        max_turns=4,
    )
    return {
        "available": True,
        "agent_name": result.agent_name,
        "tool_count": result.tool_count,
        "turn_count": result.turn_count,
        "stop_reason": result.stop_reason,
        "summary_preview": result.summary[:260],
        "session_path": result.session_path,
    }


def _task_check(runtime: HarnessRuntime) -> dict[str, object]:
    create_result = runtime.execute_tool(
        "task_control",
        {
            "action": "create_shell",
            "command": f'"{sys.executable}" -c "print(\'task smoke ok\')"',
            "description": "live workbench smoke task",
        },
    )
    if create_result.is_error:
        return {"is_error": True, "preview": create_result.output[:240]}
    payload = json.loads(create_result.output)
    task_id = str(payload["id"])
    wait_result = runtime.execute_tool("task_control", {"action": "wait", "id": task_id, "timeout_s": 10})
    output_result = runtime.execute_tool("task_control", {"action": "output", "id": task_id, "max_bytes": 2000})
    return {
        "is_error": False,
        "task_id": task_id,
        "wait_preview": wait_result.output[:220],
        "output_preview": output_result.output[:220],
    }


def _self_evolution_check(runtime: HarnessRuntime) -> dict[str, object]:
    from evo_harness.harness import plan_from_saved_session

    plan = plan_from_saved_session(runtime.workspace, capabilities=_build_capabilities())
    execution = ControlledEvolutionExecutor().execute(
        plan,
        workspace_root=runtime.workspace,
        mode="candidate",
        run_validation=False,
    )
    return {
        "operator": plan.proposal.operator,
        "safe_to_apply": plan.safe_to_apply,
        "success": execution.success,
        "created_paths": execution.created_paths,
        "promotion_state": execution.promotion_state,
    }


def main() -> None:
    enable_utf8_console()
    parser = argparse.ArgumentParser(description="Run a live provider smoke workbench against a disposable Evo workspace.")
    parser.add_argument("--provider", required=True, help="Provider/profile name, e.g. moonshot or openai-compatible.")
    parser.add_argument("--model", required=True, help="Model name.")
    parser.add_argument("--api-key-env", required=True, help="Environment variable containing the API key.")
    parser.add_argument("--base-url", help="Optional base URL override.")
    parser.add_argument("--workspace-out", help="Optional persistent output workspace path.")
    parser.add_argument(
        "--source-workspace",
        default=str(REPO_ROOT),
        help="Workspace template copied into a disposable test directory before running checks.",
    )
    parser.add_argument("--max-turns", type=int, default=4, help="Maximum live query turns.")
    parser.add_argument(
        "--prompt",
        default="Inspect the workspace ecosystem, use tools to examine the top-level layout and CLAUDE.md, then summarize what is available.",
        help="Prompt used for the live query smoke test.",
    )
    args = parser.parse_args()

    if not os.environ.get(args.api_key_env):
        raise SystemExit(f"Missing API key environment variable: {args.api_key_env}")

    workspace_target = Path(args.workspace_out).resolve() if args.workspace_out else None
    tempdir: tempfile.TemporaryDirectory[str] | None = None
    if workspace_target is None:
        tempdir = tempfile.TemporaryDirectory(prefix="evo-live-workbench-")
        workspace_target = Path(tempdir.name) / "workspace"

    try:
        workspace = _copy_workspace(Path(args.source_workspace).resolve(), workspace_target)
        summary_runtime = HarnessRuntime(workspace)
        ecosystem_runtime = HarnessRuntime(workspace)
        tool_runtime = HarnessRuntime(workspace)
        mcp_runtime = HarnessRuntime(workspace)
        live_runtime = HarnessRuntime(workspace)
        subagent_runtime = HarnessRuntime(workspace)
        task_runtime = HarnessRuntime(workspace)
        provider = build_live_provider(
            settings=live_runtime.settings,
            provider_override=args.provider,
            model_override=args.model,
            api_key_env_override=args.api_key_env,
            base_url_override=args.base_url,
        )
        subagent_provider = build_live_provider(
            settings=subagent_runtime.settings,
            provider_override=args.provider,
            model_override=args.model,
            api_key_env_override=args.api_key_env,
            base_url_override=args.base_url,
        )
        report = {
            "workspace_summary": _workspace_summary(summary_runtime),
            "ecosystem_checks": _ecosystem_checks(ecosystem_runtime),
            "direct_tool_checks": _direct_tool_checks(tool_runtime),
            "mcp_checks": _mcp_checks(mcp_runtime),
            "live_query": _live_query_check(live_runtime, provider=provider, prompt=args.prompt, max_turns=args.max_turns),
            "subagent": _subagent_check(subagent_runtime, provider=subagent_provider),
            "task_control": _task_check(task_runtime),
            "self_evolution": _self_evolution_check(live_runtime),
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))
    finally:
        if tempdir is not None:
            tempdir.cleanup()


if __name__ == "__main__":
    main()
