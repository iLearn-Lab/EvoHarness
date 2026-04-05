from __future__ import annotations

from pathlib import Path
from typing import Any

from evo_harness.engine import EvolutionEngine
from evo_harness.harness.session import load_session_snapshot
from evo_harness.models import EvolutionPlan, HarnessCapabilities, Outcome, TaskTrace


def task_trace_from_session_snapshot(snapshot: dict[str, Any]) -> TaskTrace:
	metadata = dict(snapshot.get("metadata", {}))
	tool_history = list(metadata.get("tool_history", []))
	messages = list(snapshot.get("messages", []))
	active_command = metadata.get("active_command") or {}
	query_stats = dict(metadata.get("query_stats", {}))
	usage = dict(snapshot.get("usage", {}))
	stop_reason = str(metadata.get("stop_reason", "") or "")

	error_records = [item for item in tool_history if item.get("result", {}).get("is_error")]
	repeated_failures = len(error_records)
	error_tags = _derive_error_tags(
		error_records,
		active_command=active_command,
		query_stats=query_stats,
		stop_reason=stop_reason,
		tool_history=tool_history,
		total_tool_calls=int(usage.get("tool_calls", len(tool_history))),
	)

	if error_records:
		outcome = Outcome.FAILURE
	elif stop_reason in {
		"max_consecutive_tool_rounds",
		"max_empty_assistant_turns",
		"repeated_tool_signature",
		"max_total_tool_calls",
		"tool_calls",
	}:
		outcome = Outcome.PARTIAL
	elif {"command_policy_pressure", "context_pressure", "exploration_loop", "ecosystem_gap", "provider_stall"} & set(error_tags):
		outcome = Outcome.PARTIAL
	else:
		outcome = Outcome.SUCCESS

	summary = _best_summary(messages, active_command)
	reusable_success_pattern = outcome == Outcome.SUCCESS and len(tool_history) >= 2
	validation_targets = _infer_validation_targets(snapshot)
	artifacts = {
		"active_command_name": active_command.get("name"),
		"active_command_path": active_command.get("path"),
		"active_command_source": active_command.get("source"),
		"last_tool_name": tool_history[-1]["tool_name"] if tool_history else None,
		"tool_error_count": len(error_records),
		"query_stop_reason": stop_reason,
		"query_turn_count": metadata.get("turn_count"),
		"context_truncations": query_stats.get("context_truncations", 0),
		"context_compactions": query_stats.get("context_compactions", 0),
		"mutating_tool_calls": query_stats.get("mutating_tool_calls", 0),
		"mutating_tool_failures": query_stats.get("mutating_tool_failures", 0),
	}
	if "context_pressure" in error_tags or "exploration_loop" in error_tags:
		artifacts["skill_name"] = "long-context-retrieval"
	if "provider_stall" in error_tags:
		artifacts["skill_name"] = "live-provider-debugging"
	if "ecosystem_gap" in error_tags:
		artifacts["bundle_name"] = "growth-planning"

	return TaskTrace(
		task_id=str(snapshot.get("session_id", "latest")),
		harness="evo-harness",
		outcome=outcome,
		summary=summary,
		repeated_failures=repeated_failures,
		reusable_success_pattern=reusable_success_pattern,
		error_tags=error_tags,
		tool_calls=int(usage.get("tool_calls", len(tool_history))),
		token_cost=0,
		token_budget=0,
		validation_targets=validation_targets,
		artifacts=artifacts,
	)


def plan_from_session_snapshot(
	snapshot: dict[str, Any],
	*,
	capabilities: HarnessCapabilities,
	workspace_root: str | Path,
) -> EvolutionPlan:
	trace = task_trace_from_session_snapshot(snapshot)
	return EvolutionEngine().plan(
		trace=trace,
		capabilities=capabilities,
		workspace_root=workspace_root,
	)


def plan_from_saved_session(
	workspace: str | Path,
	*,
	capabilities: HarnessCapabilities,
	session_id: str = "latest",
) -> EvolutionPlan:
	snapshot = load_session_snapshot(workspace, session_id)
	if snapshot is None:
		raise FileNotFoundError(f"No session snapshot found for {session_id}")
	return plan_from_session_snapshot(
		snapshot,
		capabilities=capabilities,
		workspace_root=workspace,
	)


def _best_summary(messages: list[dict[str, Any]], active_command: dict[str, Any]) -> str:
	for role in ("assistant", "user"):
		for message in reversed(messages):
			if message.get("role") == role and str(message.get("text", "")).strip():
				return str(message["text"]).strip()[:240]
	command_name = active_command.get("name")
	if command_name:
		return f"Session executed under command {command_name}."
	return "Session completed without a detailed summary."


def _derive_error_tags(
	error_records: list[dict[str, Any]],
	*,
	active_command: dict[str, Any],
	query_stats: dict[str, Any],
	stop_reason: str,
	tool_history: list[dict[str, Any]],
	total_tool_calls: int,
) -> list[str]:
	tags: set[str] = set()
	for item in error_records:
		result = dict(item.get("result", {}))
		output = str(result.get("output", "")).lower()
		metadata = dict(result.get("metadata", {}))
		tool_name = str(item.get("tool_name", ""))
		if "permission denied" in output:
			tags.add("permission_denied")
		if metadata.get("requires_confirmation"):
			tags.add("confirmation_required")
		if metadata.get("blocked_by_command"):
			tags.add("command_policy_violation")
			tags.add("tool_misuse")
		if metadata.get("blocked_by_safety_pattern"):
			tags.add("safety_block")
		if "unknown tool" in output:
			tags.add("missing_skill")
		if tool_name == "bash":
			tags.add("tool_misuse")

	if query_stats.get("context_truncations") or query_stats.get("context_compactions"):
		tags.add("context_pressure")
	if stop_reason in {"max_consecutive_tool_rounds", "repeated_tool_signature", "tool_calls"} and total_tool_calls >= 6:
		tags.add("exploration_loop")
	if stop_reason == "max_empty_assistant_turns":
		tags.add("provider_stall")
	if _looks_like_ecosystem_gap(active_command=active_command, tool_history=tool_history, total_tool_calls=total_tool_calls):
		tags.add("ecosystem_gap")
	if _looks_like_command_pressure(active_command=active_command, error_records=error_records, query_stats=query_stats):
		tags.add("command_policy_pressure")
		tags.add("command_policy_violation")
	if _tool_history_calls(tool_history, "run_subagent") >= 2:
		tags.add("subagent_pressure")
	return sorted(tags)


def _infer_validation_targets(snapshot: dict[str, Any]) -> list[str]:
	text_blobs = [str(snapshot.get("system_prompt", ""))]
	for message in snapshot.get("messages", []):
		text_blobs.append(str(message.get("text", "")))
	joined = "\n".join(text_blobs)
	targets: list[str] = []
	for candidate in ("python -m unittest", "pytest", "npm test"):
		if candidate in joined:
			targets.append(candidate)
	return targets


def _looks_like_command_pressure(
	*,
	active_command: dict[str, Any],
	error_records: list[dict[str, Any]],
	query_stats: dict[str, Any],
) -> bool:
	command_name = str(active_command.get("name", "") or "")
	if not _command_is_read_only(command_name):
		return False
	if int(query_stats.get("mutating_tool_calls", 0) or 0) > 0:
		return True
	if int(query_stats.get("mutating_tool_failures", 0) or 0) > 0:
		return True
	for item in error_records:
		result = dict(item.get("result", {}))
		metadata = dict(result.get("metadata", {}))
		if metadata.get("blocked_by_command"):
			return True
	return False


def _looks_like_ecosystem_gap(
	*,
	active_command: dict[str, Any],
	tool_history: list[dict[str, Any]],
	total_tool_calls: int,
) -> bool:
	if active_command.get("name"):
		return False
	if total_tool_calls < 5:
		return False
	discovery_tools = {
		"workspace_status",
		"list_registry",
		"tool_help",
		"skill",
		"render_command",
		"mcp_registry_detail",
		"mcp_call_tool",
		"mcp_read_resource",
		"mcp_get_prompt",
		"run_subagent",
	}
	discovery_count = sum(1 for item in tool_history if str(item.get("tool_name", "")) in discovery_tools)
	return discovery_count >= max(3, total_tool_calls // 2)


def _command_is_read_only(command_name: str) -> bool:
	lowered = command_name.lower()
	return "read-only" in lowered or "inspect" in lowered or "scan" in lowered


def _tool_history_calls(tool_history: list[dict[str, Any]], tool_name: str) -> int:
	return sum(1 for item in tool_history if str(item.get("tool_name", "")) == tool_name)
