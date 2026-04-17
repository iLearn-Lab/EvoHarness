from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from evo_harness.engine import EvolutionEngine
from evo_harness.harness.provider import detect_provider_profile
from evo_harness.harness.session import get_session_dir, load_session_snapshot
from evo_harness.models import AutonomousEvolutionAssessment, EvolutionPlan, HarnessCapabilities, Outcome, TaskTrace


def task_trace_from_session_snapshot(
    snapshot: dict[str, Any],
    *,
    workspace: str | Path | None = None,
    assessment: AutonomousEvolutionAssessment | None = None,
) -> TaskTrace:
    effective_snapshot = _snapshot_with_assessment(snapshot, assessment)
    metadata = dict(effective_snapshot.get("metadata", {}))
    tool_history = list(metadata.get("tool_history", []))
    messages = list(effective_snapshot.get("messages", []))
    active_command = metadata.get("active_command") or {}
    query_stats = dict(metadata.get("query_stats", {}))
    usage = dict(effective_snapshot.get("usage", {}))
    stop_reason = str(metadata.get("stop_reason", "") or "")
    assessment_payload = _coerce_assessment(metadata.get("autonomous_evolution_assessment"))

    error_records = [item for item in tool_history if item.get("result", {}).get("is_error")]
    error_tags = _derive_error_tags(
        error_records,
        active_command=active_command,
        assessment=assessment_payload,
        query_stats=query_stats,
        stop_reason=stop_reason,
        tool_history=tool_history,
        total_tool_calls=int(usage.get("tool_calls", len(tool_history))),
    )
    historical_similar_failures = _historical_similar_failure_count(
        effective_snapshot,
        workspace=workspace,
        current_error_tags=error_tags,
        active_command=active_command,
        assessment=assessment_payload,
    )
    current_failure_like = bool(
        error_records
        or (assessment_payload and assessment_payload.outcome in {Outcome.FAILURE.value, Outcome.PARTIAL.value})
        or stop_reason in {
            "max_consecutive_tool_rounds",
            "max_empty_assistant_turns",
            "repeated_tool_signature",
            "max_total_tool_calls",
            "tool_calls",
        }
        or {"command_policy_pressure", "context_pressure", "exploration_loop", "ecosystem_gap", "provider_stall"} & set(error_tags)
    )
    repeated_failures = historical_similar_failures + (1 if current_failure_like else 0)

    if assessment_payload and assessment_payload.outcome in {Outcome.FAILURE.value, Outcome.PARTIAL.value}:
        outcome = Outcome(assessment_payload.outcome)
    elif error_records:
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

    summary = (
        assessment_payload.summary
        if assessment_payload and assessment_payload.summary
        else _best_summary(messages, active_command)
    )
    reusable_success_pattern = bool(
        outcome == Outcome.SUCCESS
        and len(tool_history) >= 2
        and not (assessment_payload and assessment_payload.capability_gap)
        and not (assessment_payload and assessment_payload.needs_evolution and assessment_payload.operator != "distill_memory")
    )
    validation_targets = _infer_validation_targets(effective_snapshot)
    provider_config = _provider_config_from_snapshot(effective_snapshot, metadata)
    artifacts = {
        "active_command_name": active_command.get("name"),
        "active_command_path": active_command.get("path"),
        "active_command_source": active_command.get("source"),
        "active_command_arguments": metadata.get("active_command_arguments", ""),
        "provider_config": provider_config,
        "last_tool_name": tool_history[-1]["tool_name"] if tool_history else None,
        "tool_error_count": len(error_records),
        "query_stop_reason": stop_reason,
        "query_turn_count": metadata.get("turn_count"),
        "context_truncations": query_stats.get("context_truncations", 0),
        "context_compactions": query_stats.get("context_compactions", 0),
        "mutating_tool_calls": query_stats.get("mutating_tool_calls", 0),
        "mutating_tool_failures": query_stats.get("mutating_tool_failures", 0),
        "initial_user_prompt": _first_user_prompt(messages),
        "session_error_count": len(error_records),
        "historical_similar_failures": historical_similar_failures,
    }
    if "context_pressure" in error_tags or "exploration_loop" in error_tags:
        artifacts["skill_name"] = "long-context-retrieval"
    if "provider_stall" in error_tags:
        artifacts["skill_name"] = "live-provider-debugging"
    if "ecosystem_gap" in error_tags:
        artifacts["bundle_name"] = "growth-planning"
    if assessment_payload is not None:
        artifacts["autonomous_evolution_assessment"] = assessment_payload.to_dict()
        if assessment_payload.capability_gap is not None:
            artifacts["capability_gap"] = dict(assessment_payload.capability_gap)
            if not artifacts.get("bundle_name"):
                artifacts["bundle_name"] = "capability-growth"
            elif artifacts.get("bundle_name") == "growth-planning" and not assessment_payload.bundle_name:
                artifacts["bundle_name"] = "capability-growth"
        if assessment_payload.bundle_name:
            artifacts["bundle_name"] = assessment_payload.bundle_name
        if assessment_payload.skill_name:
            artifacts["skill_name"] = assessment_payload.skill_name
        if assessment_payload.operator:
            artifacts["requested_operator"] = assessment_payload.operator
        if assessment_payload.replay_prompt:
            artifacts["replay_prompt"] = assessment_payload.replay_prompt

    return TaskTrace(
        task_id=str(effective_snapshot.get("session_id", "latest")),
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
    assessment: AutonomousEvolutionAssessment | None = None,
) -> EvolutionPlan:
    trace = task_trace_from_session_snapshot(snapshot, workspace=workspace_root, assessment=assessment)
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
    assessment: AutonomousEvolutionAssessment | None = None,
) -> EvolutionPlan:
    snapshot = load_session_snapshot(workspace, session_id)
    if snapshot is None:
        raise FileNotFoundError(f"No session snapshot found for {session_id}")
    resolved_assessment = assessment or _coerce_assessment(dict(snapshot.get("metadata", {})).get("autonomous_evolution_assessment"))
    if resolved_assessment is None:
        resolved_assessment = _assess_snapshot_with_inferred_provider(snapshot, workspace=workspace)
    return plan_from_session_snapshot(
        snapshot,
        capabilities=capabilities,
        workspace_root=workspace,
        assessment=resolved_assessment,
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


def _first_user_prompt(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        if message.get("role") == "user" and str(message.get("text", "")).strip():
            return str(message["text"]).strip()
    return ""


def _derive_error_tags(
    error_records: list[dict[str, Any]],
    *,
    active_command: dict[str, Any],
    assessment: AutonomousEvolutionAssessment | None,
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
        if "module not found" in output or "no module named" in output:
            tags.add("missing_skill")
        if tool_name == "bash":
            tags.add("tool_misuse")

    if assessment is not None:
        tags.update(str(tag).strip() for tag in assessment.error_tags if str(tag).strip())
        if assessment.capability_gap is not None:
            tags.add("capability_gap")
            tags.add("ecosystem_gap")
        if assessment.operator == "revise_command":
            tags.add("command_gap")
        if assessment.operator == "revise_skill":
            tags.add("skill_gap")
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
    metadata = dict(snapshot.get("metadata", {}))
    assessment = _coerce_assessment(metadata.get("autonomous_evolution_assessment"))
    text_blobs = [str(snapshot.get("system_prompt", ""))]
    for message in snapshot.get("messages", []):
        text_blobs.append(str(message.get("text", "")))
    for item in metadata.get("tool_history", []):
        result = dict(item.get("result", {}))
        text_blobs.append(str(result.get("output", "")))
    joined = "\n".join(text_blobs)
    targets: list[str] = []
    if assessment is not None and assessment.capability_gap is not None:
        for item in assessment.capability_gap.get("validation_targets", []):
            text = str(item).strip()
            if text and text not in targets:
                targets.append(text)
    for candidate in (
        "python -m unittest",
        "pytest",
        "npm test",
        "pnpm test",
        "yarn test",
        "go test",
        "cargo test",
        "dotnet test",
        "mvn test",
        "gradle test",
        "make test",
        "python -m pytest",
    ):
        if candidate in joined and candidate not in targets:
            targets.append(candidate)
    command_patterns = (
        r"\b(?:python\s+-m\s+unittest|python\s+-m\s+pytest|pytest|npm test|pnpm test|yarn test|go test|cargo test|dotnet test|mvn test|gradle test|make test)\b",
    )
    for pattern in command_patterns:
        for match in re.findall(pattern, joined, flags=re.IGNORECASE):
            normalized = " ".join(str(match).split()).strip()
            if normalized and normalized not in targets:
                targets.append(normalized)
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


def _coerce_assessment(raw: Any) -> AutonomousEvolutionAssessment | None:
    if not isinstance(raw, dict):
        return None
    try:
        return AutonomousEvolutionAssessment(
            needs_evolution=bool(raw.get("needs_evolution", False)),
            operator=str(raw.get("operator", "stop")).strip().lower() or "stop",
            outcome=str(raw.get("outcome", Outcome.PARTIAL.value)).strip().lower(),
            confidence=float(raw.get("confidence", 0.5) or 0.5),
            summary=str(raw.get("summary", "")).strip(),
            error_tags=[str(item).strip() for item in raw.get("error_tags", []) if str(item).strip()],
            capability_gap=dict(raw.get("capability_gap")) if isinstance(raw.get("capability_gap"), dict) else None,
            skill_name=str(raw.get("skill_name")).strip() if raw.get("skill_name") else None,
            bundle_name=str(raw.get("bundle_name")).strip() if raw.get("bundle_name") else None,
            replay_prompt=str(raw.get("replay_prompt")).strip() if raw.get("replay_prompt") else None,
            evidence=[str(item).strip() for item in raw.get("evidence", []) if str(item).strip()],
            raw_response=str(raw.get("raw_response", "")).strip(),
        )
    except Exception:
        return None


def _provider_config_from_snapshot(snapshot: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    configured = dict(metadata.get("provider_config", {}) or {})
    model = str(snapshot.get("model", "") or configured.get("model", "") or "").strip()
    if not model and not configured:
        return {}

    profile = detect_provider_profile(
        provider=str(configured.get("provider", "") or "").strip() or None,
        profile=str(configured.get("profile", "") or "").strip() or None,
        base_url=str(configured.get("base_url", "") or "").strip() or None,
        model=model or None,
    )
    normalized = {
        "model": model or str(configured.get("model", "") or "").strip(),
        "provider": str(configured.get("provider", "") or profile.name).strip(),
        "profile": str(configured.get("profile", "") or profile.name).strip(),
        "api_format": str(configured.get("api_format", "") or profile.api_format).strip(),
        "api_key_env": str(configured.get("api_key_env", "") or profile.default_api_key_env).strip(),
        "base_url": str(configured.get("base_url", "") or profile.default_base_url).strip(),
        "auth_scheme": str(configured.get("auth_scheme", "") or profile.auth_scheme).strip(),
        "headers": dict(configured.get("headers", {}) or {}),
    }
    return {key: value for key, value in normalized.items() if value or key == "headers"}


def _assess_snapshot_with_inferred_provider(
    snapshot: dict[str, Any],
    *,
    workspace: str | Path,
) -> AutonomousEvolutionAssessment | None:
    from evo_harness.autonomous_evolution import assess_session_snapshot
    from evo_harness.harness.settings import load_settings

    workspace_root = Path(workspace).resolve()
    settings = load_settings(workspace=workspace_root)
    provider_config = _provider_config_from_snapshot(snapshot, dict(snapshot.get("metadata", {})))
    # When replaying or reassessing an archived session, prefer the inferred provider env var
    # over any stale workspace-saved inline API key from another provider.
    settings.provider.api_key = None
    if provider_config.get("model"):
        settings.model = str(provider_config["model"])
    if provider_config.get("provider"):
        settings.provider.provider = str(provider_config["provider"])
    if provider_config.get("profile"):
        settings.provider.profile = str(provider_config["profile"])
    if provider_config.get("api_format"):
        settings.provider.api_format = str(provider_config["api_format"])
    if provider_config.get("api_key_env"):
        settings.provider.api_key_env = str(provider_config["api_key_env"])
    if provider_config.get("base_url"):
        settings.provider.base_url = str(provider_config["base_url"])
    if provider_config.get("auth_scheme"):
        settings.provider.auth_scheme = str(provider_config["auth_scheme"])
    if isinstance(provider_config.get("headers"), dict):
        settings.provider.headers = {str(key): str(value) for key, value in provider_config["headers"].items()}
    try:
        return assess_session_snapshot(snapshot, workspace=workspace_root, settings=settings)
    except Exception:
        return None


def _historical_similar_failure_count(
    snapshot: dict[str, Any],
    *,
    workspace: str | Path | None,
    current_error_tags: list[str],
    active_command: dict[str, Any],
    assessment: AutonomousEvolutionAssessment | None,
    limit: int = 20,
) -> int:
    if workspace is None:
        return 0
    session_dir = get_session_dir(workspace)
    if not session_dir.exists():
        return 0

    current_metadata = dict(snapshot.get("metadata", {}))
    current_stop_reason = str(current_metadata.get("stop_reason", "") or "").strip()
    current_labels = {
        str(active_command.get("name", "") or "").strip(),
        str((assessment.bundle_name if assessment is not None else "") or "").strip(),
        str((assessment.skill_name if assessment is not None else "") or "").strip(),
        str(((assessment.capability_gap or {}).get("name") if assessment is not None and assessment.capability_gap else "") or "").strip(),
    }
    current_labels.discard("")
    current_session_ids = {
        str(snapshot.get("session_id", "") or "").strip(),
        str(snapshot.get("archive_session_id", "") or "").strip(),
    }
    current_tags = {str(item).strip() for item in current_error_tags if str(item).strip()}
    matches = 0
    for path in sorted(session_dir.glob("*.json"), reverse=True):
        if path.stem == "latest" or path.name.endswith(".rollback.json"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        payload_session_id = str(payload.get("session_id", "") or "").strip()
        if payload_session_id in current_session_ids:
            continue
        metadata = dict(payload.get("metadata", {}))
        tool_history = list(metadata.get("tool_history", []))
        usage = dict(payload.get("usage", {}))
        assessment_payload = _coerce_assessment(metadata.get("autonomous_evolution_assessment"))
        error_records = [item for item in tool_history if dict(item.get("result", {})).get("is_error")]
        prior_tags = set(
            _derive_error_tags(
                error_records,
                active_command=dict(metadata.get("active_command") or {}),
                assessment=assessment_payload,
                query_stats=dict(metadata.get("query_stats", {})),
                stop_reason=str(metadata.get("stop_reason", "") or ""),
                tool_history=tool_history,
                total_tool_calls=int(usage.get("tool_calls", len(tool_history))),
            )
        )
        prior_labels = {
            str(dict(metadata.get("active_command") or {}).get("name", "") or "").strip(),
            str((assessment_payload.bundle_name if assessment_payload is not None else "") or "").strip(),
            str((assessment_payload.skill_name if assessment_payload is not None else "") or "").strip(),
            str(((assessment_payload.capability_gap or {}).get("name") if assessment_payload is not None and assessment_payload.capability_gap else "") or "").strip(),
        }
        prior_labels.discard("")
        prior_outcome = _historical_outcome(payload, prior_tags, assessment_payload)
        if prior_outcome not in {Outcome.FAILURE.value, Outcome.PARTIAL.value}:
            continue
        similar = False
        if current_labels and prior_labels and current_labels & prior_labels:
            similar = True
        elif current_tags and prior_tags and current_tags & prior_tags:
            similar = True
        elif current_stop_reason and current_stop_reason == str(metadata.get("stop_reason", "") or "").strip() and current_stop_reason != "end_turn":
            similar = True
        if similar:
            matches += 1
            if matches >= limit:
                break
    return matches


def _historical_outcome(
    snapshot: dict[str, Any],
    error_tags: set[str],
    assessment: AutonomousEvolutionAssessment | None,
) -> str:
    metadata = dict(snapshot.get("metadata", {}))
    tool_history = list(metadata.get("tool_history", []))
    if assessment is not None and assessment.outcome in {Outcome.FAILURE.value, Outcome.PARTIAL.value, Outcome.SUCCESS.value}:
        return assessment.outcome
    if any(dict(item.get("result", {})).get("is_error") for item in tool_history):
        return Outcome.FAILURE.value
    stop_reason = str(metadata.get("stop_reason", "") or "").strip()
    if stop_reason in {
        "max_consecutive_tool_rounds",
        "max_empty_assistant_turns",
        "repeated_tool_signature",
        "max_total_tool_calls",
        "tool_calls",
    }:
        return Outcome.PARTIAL.value
    if {"command_policy_pressure", "context_pressure", "exploration_loop", "ecosystem_gap", "provider_stall"} & error_tags:
        return Outcome.PARTIAL.value
    return Outcome.SUCCESS.value


def _snapshot_with_assessment(
    snapshot: dict[str, Any],
    assessment: AutonomousEvolutionAssessment | None,
) -> dict[str, Any]:
    if assessment is None:
        return snapshot
    cloned = json.loads(json.dumps(snapshot))
    metadata = dict(cloned.get("metadata", {}))
    metadata["autonomous_evolution_assessment"] = assessment.to_dict()
    cloned["metadata"] = metadata
    return cloned
