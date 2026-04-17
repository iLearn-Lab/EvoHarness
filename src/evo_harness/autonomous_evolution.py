from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evo_harness.models import AutonomousEvolutionAssessment, Outcome
from evo_harness.harness.messages import ChatMessage
from evo_harness.harness.memory import add_memory_entry
from evo_harness.harness.provider import BaseProvider, build_live_provider
from evo_harness.harness.runtime import HarnessRuntime
from evo_harness.harness.session import load_session_snapshot
from evo_harness.operators.grow_ecosystem import ecosystem_bundle_catalog, ecosystem_bundle_exists


def assess_saved_session(
    workspace: str | Path,
    *,
    settings,
    provider: BaseProvider | None = None,
    session_id: str = "latest",
) -> AutonomousEvolutionAssessment:
    snapshot = load_session_snapshot(workspace, session_id=session_id)
    if snapshot is None:
        raise FileNotFoundError(f"No session snapshot found for {session_id}")
    return assess_session_snapshot(
        snapshot,
        workspace=workspace,
        settings=settings,
        provider=provider,
    )


def assess_session_snapshot(
    snapshot: dict[str, Any],
    *,
    workspace: str | Path,
    settings,
    provider: BaseProvider | None = None,
) -> AutonomousEvolutionAssessment:
    runtime = HarnessRuntime(workspace)
    assessment_provider = _prepare_assessment_provider(provider or build_live_provider(settings=settings))
    turn = None
    prompts = [
        _build_assessment_prompt(snapshot, runtime, compact=True),
        _build_assessment_prompt(snapshot, runtime, compact=False),
    ]
    errors: list[str] = []
    for index, prompt in enumerate(prompts):
        active_provider = assessment_provider if index == 0 else _clone_provider(assessment_provider)
        try:
            turn = active_provider.next_turn(
                system_prompt=_ASSESSMENT_SYSTEM_PROMPT,
                messages=[ChatMessage(role="user", text=prompt)],
                tool_schema=[],
            )
            break
        except Exception as exc:
            errors.append(str(exc))
    if turn is None:
        raise RuntimeError("Autonomous assessment failed: " + " | ".join(errors))
    raw_text = str(turn.assistant_text or "").strip()
    payload = _parse_assessment_payload_with_repair(raw_text, provider=assessment_provider)
    assessment = AutonomousEvolutionAssessment(
        needs_evolution=bool(payload.get("needs_evolution", False)),
        operator=str(payload.get("operator", "stop")).strip().lower() or "stop",
        outcome=_normalize_outcome(str(payload.get("outcome", "partial"))),
        confidence=_coerce_confidence(payload.get("confidence", 0.5)),
        summary=str(payload.get("summary", "")).strip(),
        error_tags=[str(item).strip() for item in payload.get("error_tags", []) if str(item).strip()],
        capability_gap=_normalize_capability_gap(payload.get("capability_gap")),
        skill_name=_optional_text(payload.get("skill_name")),
        bundle_name=_optional_text(payload.get("bundle_name")),
        replay_prompt=_optional_text(payload.get("replay_prompt")),
        evidence=[str(item).strip() for item in payload.get("evidence", []) if str(item).strip()],
        raw_response=raw_text + (f"\n\n[assessment_retries] {' | '.join(errors)}" if errors else ""),
    )
    _compile_capability_gap(
        snapshot,
        runtime=runtime,
        assessment=assessment,
        provider=assessment_provider,
    )
    return _finalize_assessment(assessment, provider=assessment_provider)


def _prepare_assessment_provider(provider: BaseProvider) -> BaseProvider:
    prepared = _clone_provider(provider)
    if hasattr(prepared, "max_tokens"):
        try:
            prepared.max_tokens = min(int(getattr(prepared, "max_tokens", 2048) or 2048), 2048)
        except Exception:
            pass
    if hasattr(prepared, "request_timeout_seconds"):
        try:
            prepared.request_timeout_seconds = max(int(getattr(prepared, "request_timeout_seconds", 0) or 0), 180)
        except Exception:
            pass
    if hasattr(prepared, "max_retries"):
        try:
            prepared.max_retries = max(int(getattr(prepared, "max_retries", 0) or 0), 2)
        except Exception:
            pass
    return prepared


def _parse_assessment_payload_with_repair(text: str, *, provider: BaseProvider) -> dict[str, Any]:
    try:
        payload = _parse_assessment_payload(text)
        if _assessment_payload_looks_implausible(payload, raw_text=text):
            repaired = _repair_assessment_payload(text, provider=provider)
            if repaired is not None:
                return repaired
        return payload
    except Exception:
        repaired = _repair_assessment_payload(text, provider=provider)
        if repaired is not None:
            return repaired
        raise


def _parse_completion_payload_with_repair(text: str, *, provider: BaseProvider) -> dict[str, Any]:
    try:
        payload = _parse_completion_payload(text)
        if _completion_payload_looks_implausible(payload):
            repaired = _repair_completion_payload(text, provider=provider)
            if repaired is not None:
                return repaired
        return payload
    except Exception:
        repaired = _repair_completion_payload(text, provider=provider)
        if repaired is not None:
            return repaired
        raise


def _finalize_assessment(
    assessment: AutonomousEvolutionAssessment,
    *,
    provider: BaseProvider,
) -> AutonomousEvolutionAssessment:
    if assessment.capability_gap is None:
        return assessment
    if assessment.bundle_name and ecosystem_bundle_exists(assessment.bundle_name):
        return assessment
    if assessment.bundle_name and not ecosystem_bundle_exists(assessment.bundle_name):
        assessment.bundle_name = None
    capability_bundle = str(assessment.capability_gap.get("bundle_name", "") or "").strip()
    if capability_bundle and ecosystem_bundle_exists(capability_bundle):
        assessment.bundle_name = capability_bundle
        return assessment
    if capability_bundle and not ecosystem_bundle_exists(capability_bundle):
        assessment.capability_gap.pop("bundle_name", None)
    bundle_name = _resolve_existing_bundle_name(assessment, provider=provider)
    if not bundle_name:
        return assessment
    assessment.bundle_name = bundle_name
    assessment.capability_gap["bundle_name"] = bundle_name
    return assessment


def snapshot_with_assessment(snapshot: dict[str, Any], assessment: AutonomousEvolutionAssessment | None) -> dict[str, Any]:
    if assessment is None:
        return snapshot
    cloned = json.loads(json.dumps(snapshot))
    metadata = dict(cloned.get("metadata", {}))
    metadata["autonomous_evolution_assessment"] = assessment.to_dict()
    cloned["metadata"] = metadata
    return cloned


def run_autonomous_self_evolution(
    workspace: str | Path,
    *,
    settings,
    provider: BaseProvider | None = None,
    session_id: str = "latest",
    mode: str | None = None,
) -> dict[str, Any]:
    workspace_root = Path(workspace).resolve()
    snapshot = load_session_snapshot(workspace_root, session_id=session_id)
    if snapshot is None:
        raise FileNotFoundError(f"No session snapshot found for {session_id}")
    runtime = HarnessRuntime(workspace_root)
    completion_assessment = _completion_assessment_with_ai_or_fallback(
        snapshot,
        workspace=workspace_root,
        settings=settings,
        provider=provider,
    )
    trigger = _autonomous_trigger_decision(
        snapshot,
        workspace=workspace_root,
        settings=settings,
        completion=completion_assessment,
    )
    record: dict[str, Any] = {
        "workspace": str(workspace_root),
        "session_id": session_id,
        "trigger": trigger,
    }
    if not trigger.get("attempt", False):
        record["status"] = "skipped"
        record["notes"] = [str(trigger.get("reason", "") or "Session did not meet the autonomous evolution trigger threshold.")]
        failure_artifacts = _write_failure_learning_artifacts(
            workspace_root,
            snapshot=snapshot,
            reason=str(trigger.get("reason", "") or "Autonomous self-evolution skipped before planning."),
            completion=trigger.get("task_completion"),
        )
        if failure_artifacts:
            record["failure_learning_artifacts"] = failure_artifacts
            record.setdefault("notes", []).append(
                "The user task still looked failed or unfinished, so a reusable recovery memory and playbook were materialized."
            )
            recovery_attempt = _run_failure_recovery_session(
                workspace_root,
                snapshot=snapshot,
                settings=settings,
                provider=provider,
                failure_artifacts=failure_artifacts,
                completion=trigger.get("task_completion"),
            )
            if recovery_attempt:
                record["failure_recovery_attempt"] = recovery_attempt
                if recovery_attempt.get("completed"):
                    record.setdefault("notes", []).append(
                        "A follow-up autonomous recovery session retried the failed task without waiting for another user turn."
                    )
        record["record_path"] = str(_write_autonomous_record(workspace_root, record))
        return record
    capabilities = runtime.evolution_capabilities()
    if provider is None and not capabilities.replay_validation:
        record["status"] = "skipped"
        record["notes"] = [
            "Skipped autonomous self-evolution because no live provider credentials were available for assessment or replay validation."
        ]
        record["record_path"] = str(_write_autonomous_record(workspace_root, record))
        return record
    assessment = assess_saved_session(
        workspace_root,
        settings=settings,
        provider=provider,
        session_id=session_id,
    )
    record["assessment"] = assessment.to_dict()
    if not assessment.needs_evolution or assessment.operator == "stop":
        record["status"] = "stop"
        record["notes"] = ["Assessment decided that no self-evolution step should run."]
        record["record_path"] = str(_write_autonomous_record(workspace_root, record))
        return record

    from evo_harness.harness.evolution_bridge import plan_from_saved_session
    from evo_harness.execution import ControlledEvolutionExecutor, write_execution_record

    plan = plan_from_saved_session(
        workspace_root,
        capabilities=capabilities,
        session_id=session_id,
        assessment=assessment,
    )
    normalized_mode = (mode or settings.runtime.auto_self_evolution_mode or "candidate").lower()
    if normalized_mode in {"", "off"}:
        normalized_mode = "candidate"
    execution = ControlledEvolutionExecutor().execute(
        plan,
        workspace_root=workspace_root,
        mode=normalized_mode,
        run_validation=normalized_mode in {"apply", "promote", "auto"},
        allow_unvalidated_promotion=False,
    )
    record["status"] = "executed"
    record["plan"] = plan.to_dict()
    record["execution"] = execution.to_dict()
    execution_record_path = write_execution_record(
        workspace_root,
        plan=plan,
        execution=execution,
        origin="auto",
        metadata={
            "session_id": session_id,
            "requested_mode": normalized_mode,
            "trigger": trigger,
        },
    )
    record["execution_record_path"] = str(execution_record_path)
    learning_artifacts = _write_learning_fallbacks(
        workspace_root,
        snapshot=snapshot,
        assessment=assessment,
        plan=plan,
        execution=execution,
        settings=settings,
        completion=trigger.get("task_completion"),
    )
    if learning_artifacts:
        record["learning_artifacts"] = learning_artifacts
        record["usable_fallback_applied"] = True
        record.setdefault("notes", []).append(
            "The durable capability did not fully promote, so a reusable fallback playbook/memory was applied to the real workspace."
        )
    record["record_path"] = str(_write_autonomous_record(workspace_root, record))
    return record


_ASSESSMENT_SYSTEM_PROMPT = """\
You are the autonomous self-evolution controller for an LLM agent harness.
Your job is not to help the end user directly. Your job is to evaluate whether the just-finished session exposed
a weakness that deserves self-evolution, and to recommend the single best next operator.

Allowed operators:
- grow_ecosystem
- revise_skill
- revise_command
- distill_memory
- stop

Output JSON only. No markdown fences. Keep the decision grounded in concrete session evidence, not vibes.
Prefer grow_ecosystem when the agent lacked a persistent capability surface and would otherwise rediscover the same gap next session.
Prefer distill_memory only when the session mainly produced a reusable lesson and was not blocked by missing capability.
Judge execution capability, not explanation quality. If the assistant merely explained that a capability is missing, that still counts as a capability gap.
A listed command, skill, plugin, MCP surface, or tool only counts as sufficient when it appears capable of real execution for this task.
Do not mark needs_evolution=true when the current workspace surface already looks sufficient and the session simply failed to use it.
Treat one-off task artifacts or ad-hoc scripts created during the session as temporary execution paths unless they were clearly surfaced as durable, discoverable workspace capabilities.
If the task asked for future reuse, a raw script or loose file alone usually does not erase the capability gap.
If the user asked for a deliverable such as a Word report, document parsing, code execution workflow, or another persistent capability, decide whether the workspace can actually perform it now.
If the answer is "no, the workspace still cannot do it", then needs_evolution should usually be true and operator should usually be grow_ecosystem.
For capability_gap, describe the missing capability semantically rather than forcing it into a fixed category list.
When possible, include generic fields such as inputs, outputs, workflow_actions, state_targets, dependencies, validation_targets, and domain_tags.
Assume the user spoke naturally. Extract capability semantics from ordinary dialogue and tool evidence even when the user never names a formal capability.
Do not wait for the user to say "build a reusable capability" explicitly if the task clearly requires a reusable capability surface.
Preserve distinctive external system and tool names from the dialogue whenever they matter, such as kubectl, ffmpeg, Slack, vendor APIs, browser stacks, or library names.
Do not over-normalize everything into vague labels like "pipeline", "tool", or "integration" if the transcript contains more specific anchors.
"""


_CAPABILITY_COMPILER_SYSTEM_PROMPT = """\
You are the capability compiler for an LLM agent harness.
The task is already finished. Your job is to look at what happened and compile one reusable capability spec that could
help future sessions solve similar tasks more directly.

You are not solving the user's task now. You are extracting:
- the reusable capability name
- the durable surfaces worth adding
- the likely inputs, outputs, workflow actions, state targets, dependencies, and validation targets
- a research plan for learning or implementing the missing parts
- the minimal growth unit worth persisting
- an implementation contract that says what should be built or exposed
- a replay contract that says how the new surface should be validated later

Prefer preserving concrete tool or system names from the transcript over replacing them with vague abstractions.
Output JSON only.
"""


_TASK_COMPLETION_SYSTEM_PROMPT = """\
You judge whether the assistant fully completed the user's task in a finished session.
Judge task completion, not whether the conversation merely stopped.
Direct-answer tasks count as completed when the assistant clearly gives the requested final answer, even if no files were written.
Deliverable tasks count as completed only when the requested deliverables were actually produced or the tool evidence strongly shows they were produced.
Do not require the assistant to say a magic phrase like "completed" if the evidence already proves completion.
Use the transcript, tool evidence, and expected outputs together.
Output JSON only with:
{
  "completed": true|false,
  "confidence": 0.0,
  "reason": "short reason",
  "evidence": ["1-4 short evidence strings"]
}
"""


def _build_assessment_prompt(
    snapshot: dict[str, Any],
    runtime: HarnessRuntime,
    *,
    compact: bool,
) -> str:
    if compact:
        return _build_compact_assessment_prompt(snapshot, runtime)

    messages = list(snapshot.get("messages", []))
    transcript_items: list[str] = []
    transcript_limit = 8 if compact else 16
    text_limit = 320 if compact else 600
    for message in messages[-transcript_limit:]:
        role = str(message.get("role", ""))
        text = _normalize_text_for_ai(message.get("text", ""))
        if role in {"user", "assistant"} and text:
            transcript_items.append(f"{role}: {text[:text_limit]}")
    tool_history = list(dict(snapshot.get("metadata", {})).get("tool_history", []))
    tool_lines = []
    tool_limit = 6 if compact else 10
    for item in tool_history[-tool_limit:]:
        tool_name = str(item.get("tool_name", ""))
        result = dict(item.get("result", {}))
        status = "error" if result.get("is_error") else "ok"
        output = _normalize_text_for_ai(result.get("output", "")).replace("\n", " ")
        tool_lines.append(f"{tool_name} [{status}]: {output[:160 if compact else 240]}")

    workspace_summary = _runtime_surface_summary(runtime, compact=compact)
    metadata = dict(snapshot.get("metadata", {}))
    query_stats = dict(metadata.get("query_stats", {}))
    return "\n".join(
        [
            "Evaluate whether this completed session should trigger self-evolution.",
            "Decide based on real execution capability, including whether the current workspace surface already looked reusable enough.",
            "",
            "Session summary:",
            f"- stop_reason: {metadata.get('stop_reason')}",
            f"- turn_count: {metadata.get('turn_count')}",
            f"- total_tool_calls: {query_stats.get('total_tool_calls')}",
            f"- tool_failures: {query_stats.get('tool_failures')}",
            "",
            "Current workspace surface:",
            json.dumps(workspace_summary, ensure_ascii=False, indent=2),
            "",
            "Recent transcript:",
            *transcript_items,
            "",
            "Recent tool evidence:",
            *tool_lines,
            "",
            "Return JSON with fields:",
            "{",
            '  "needs_evolution": true|false,',
            '  "operator": "grow_ecosystem|revise_skill|revise_command|distill_memory|stop",',
            '  "outcome": "success|partial|failure",',
            '  "confidence": 0.0,',
            '  "summary": "short reason",',
            '  "error_tags": ["..."],',
            '  "capability_gap": {"name": "...", "bundle_name": "...", "preferred_surfaces": ["plugin","mcp"], "inputs": ["..."], "outputs": ["..."], "workflow_actions": ["..."], "state_targets": ["..."], "dependencies": ["..."], "constraints": ["..."], "validation_targets": ["..."], "domain_tags": ["..."], "evidence": ["..."]} or null,',
            '  "skill_name": "optional",',
            '  "bundle_name": "optional",',
            '  "replay_prompt": "optional prompt to replay after evolution",',
            '  "evidence": ["1-3 short evidence strings"]',
            "}",
            "Use bundle_name only when you are confident it matches an existing, purpose-built workspace bundle.",
            "If the gap is novel, leave bundle_name empty and describe the missing capability generically.",
            "If the current commands, skills, plugins, MCP assets, or tools already seem sufficient, prefer needs_evolution=false and explain why.",
        ]
    )


def _build_compact_assessment_prompt(snapshot: dict[str, Any], runtime: HarnessRuntime) -> str:
    metadata = dict(snapshot.get("metadata", {}))
    query_stats = dict(metadata.get("query_stats", {}))
    task_summary = _task_summary(snapshot)
    transcript_items = _recent_transcript_summary(snapshot, max_messages=6, text_limit=220)
    tool_lines = _important_tool_evidence(snapshot, max_items=5, text_limit=180)
    workspace_summary = _compact_surface_summary(runtime)
    return "\n".join(
        [
            "Evaluate whether this completed session should trigger self-evolution.",
            "Use only the compact structured summary below. Prefer the smallest correct judgment.",
            "",
            "Task:",
            task_summary,
            "",
            "Session facts:",
            f"- stop_reason: {metadata.get('stop_reason')}",
            f"- turn_count: {metadata.get('turn_count')}",
            f"- total_tool_calls: {query_stats.get('total_tool_calls')}",
            f"- tool_failures: {query_stats.get('tool_failures')}",
            f"- mutating_tool_calls: {query_stats.get('mutating_tool_calls')}",
            f"- mutating_tool_failures: {query_stats.get('mutating_tool_failures')}",
            "",
            "Workspace surface summary:",
            workspace_summary,
            "",
            "Recent transcript summary:",
            *transcript_items,
            "",
            "Important tool evidence:",
            *tool_lines,
            "",
            "Return JSON only with fields:",
            "{",
            '  "needs_evolution": true|false,',
            '  "operator": "grow_ecosystem|revise_skill|revise_command|distill_memory|stop",',
            '  "outcome": "success|partial|failure",',
            '  "confidence": 0.0,',
            '  "summary": "short reason",',
            '  "error_tags": ["..."],',
            '  "capability_gap": {"name": "...", "bundle_name": "...", "preferred_surfaces": ["plugin","mcp"], "inputs": ["..."], "outputs": ["..."], "workflow_actions": ["..."], "state_targets": ["..."], "dependencies": ["..."], "constraints": ["..."], "validation_targets": ["..."], "domain_tags": ["..."], "evidence": ["..."]} or null,',
            '  "skill_name": "optional",',
            '  "bundle_name": "optional",',
            '  "replay_prompt": "optional prompt to replay after evolution",',
            '  "evidence": ["1-3 short evidence strings"]',
            "}",
            "Keep the JSON compact. If the workspace already looks sufficient, prefer stop.",
        ]
    )


def _task_summary(snapshot: dict[str, Any]) -> str:
    messages = list(snapshot.get("messages", []))
    first_user = ""
    last_assistant = ""
    for message in messages:
        if str(message.get("role", "")) == "user" and str(message.get("text", "")).strip():
            first_user = _normalize_text_for_ai(message.get("text", ""))
            break
    for message in reversed(messages):
        if str(message.get("role", "")) == "assistant" and str(message.get("text", "")).strip():
            last_assistant = _normalize_text_for_ai(message.get("text", ""))
            break
    parts: list[str] = []
    if first_user:
        parts.append(f"- request: {first_user[:420]}")
    if last_assistant:
        parts.append(f"- final_assistant: {last_assistant[:420]}")
    if not parts:
        parts.append("- request: (no clear task text found)")
    return "\n".join(parts)


def _recent_transcript_summary(
    snapshot: dict[str, Any],
    *,
    max_messages: int,
    text_limit: int,
) -> list[str]:
    messages = list(snapshot.get("messages", []))
    transcript_items: list[str] = []
    for message in messages[-max_messages:]:
        role = str(message.get("role", "")).strip()
        text = _normalize_text_for_ai(message.get("text", ""))
        if role in {"user", "assistant"} and text:
            transcript_items.append(f"- {role}: {text[:text_limit]}")
    return transcript_items or ["- (no recent transcript summary available)"]


def _important_tool_evidence(
    snapshot: dict[str, Any],
    *,
    max_items: int,
    text_limit: int,
) -> list[str]:
    tool_history = list(dict(snapshot.get("metadata", {})).get("tool_history", []))
    scored: list[tuple[int, str]] = []
    for index, item in enumerate(tool_history):
        tool_name = str(item.get("tool_name", "")).strip() or "tool"
        result = dict(item.get("result", {}))
        output = _normalize_text_for_ai(result.get("output", "")).replace("\n", " ")
        if not output:
            continue
        lowered = output.lower()
        score = index
        if result.get("is_error"):
            score += 1000
        if any(token in lowered for token in ("not recognized", "error", "failed", "timeout", "invalid", "forbidden")):
            score += 500
        if any(token in lowered for token in ("wrote ", "created ", "saved ", "generated ", "found ", "located ")):
            score += 250
        scored.append((score, f"- {tool_name}: {output[:text_limit]}"))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [line for _score, line in scored[:max_items]]
    return selected or ["- (no important tool evidence available)"]


def _compact_surface_summary(runtime: HarnessRuntime) -> str:
    surface = runtime.discovery_surface(compact=True)
    counts = dict(surface.get("counts", {}))
    lines = [
        f"- counts: tools={counts.get('tools', 0)} commands={counts.get('commands', 0)} skills={counts.get('skills', 0)} agents={counts.get('agents', 0)} plugins={counts.get('plugins', 0)} mcp_servers={counts.get('mcp_servers', 0)}",
        f"- commands: {', '.join(list(surface.get('commands', []))[:6]) or '(none)'}",
        f"- skills: {', '.join(list(surface.get('skills', []))[:6]) or '(none)'}",
        f"- plugins: {', '.join(list(surface.get('plugins', []))[:6]) or '(none)'}",
        f"- mcp_servers: {', '.join(list(surface.get('mcp_servers', []))[:6]) or '(none)'}",
    ]
    return "\n".join(lines)


def _parse_assessment_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    candidates = [stripped]
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL)
    if fence_match is not None:
        candidates.insert(0, fence_match.group(1))
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first != -1 and last != -1 and first < last:
        candidates.append(stripped[first : last + 1])
    for candidate in candidates:
        payload = _parse_json_object_candidate(candidate)
        if isinstance(payload, dict):
            return payload
    raise ValueError(f"Could not parse autonomous evolution assessment JSON: {text[:400]}")


def _parse_completion_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    candidates = [stripped]
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL)
    if fence_match is not None:
        candidates.insert(0, fence_match.group(1))
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first != -1 and last != -1 and first < last:
        candidates.append(stripped[first : last + 1])
    for candidate in candidates:
        payload = _parse_json_object_candidate(candidate)
        if isinstance(payload, dict):
            return payload
    raise ValueError(f"Could not parse task completion JSON: {text[:400]}")


def _assessment_payload_looks_implausible(payload: dict[str, Any], *, raw_text: str) -> bool:
    operator = str(payload.get("operator", "") or "").strip().lower()
    summary = str(payload.get("summary", "") or "").strip()
    raw_lower = raw_text.lower()
    if operator not in {"grow_ecosystem", "revise_skill", "revise_command", "distill_memory", "stop"}:
        return True
    if "\"needs_evolution\": true" in raw_lower and not bool(payload.get("needs_evolution", False)):
        return True
    if "\"operator\":\"grow_ecosystem\"" in raw_lower.replace(" ", "") and operator != "grow_ecosystem":
        return True
    if "\"operator\":\"revise_skill\"" in raw_lower.replace(" ", "") and operator != "revise_skill":
        return True
    if "\"operator\":\"revise_command\"" in raw_lower.replace(" ", "") and operator != "revise_command":
        return True
    if not summary and bool(payload.get("needs_evolution", False)):
        return True
    return False


def _completion_payload_looks_implausible(payload: dict[str, Any]) -> bool:
    if not isinstance(payload.get("completed"), bool):
        return True
    confidence = payload.get("confidence", 0.5)
    try:
        float(confidence)
    except Exception:
        return True
    reason = str(payload.get("reason", "") or "").strip()
    evidence = payload.get("evidence", [])
    if not reason and not isinstance(evidence, list):
        return True
    return False


def _repair_assessment_payload(text: str, *, provider: BaseProvider) -> dict[str, Any] | None:
    prompt = "\n".join(
        [
            "The following assessment response was supposed to be strict JSON but was malformed or inconsistent.",
            "Rewrite it as one valid JSON object only.",
            "Required fields:",
            "{",
            '  "needs_evolution": true|false,',
            '  "operator": "grow_ecosystem|revise_skill|revise_command|distill_memory|stop",',
            '  "outcome": "success|partial|failure",',
            '  "confidence": 0.0,',
            '  "summary": "short reason",',
            '  "error_tags": ["..."],',
            '  "capability_gap": {...} or null,',
            '  "skill_name": "optional",',
            '  "bundle_name": "optional",',
            '  "replay_prompt": "optional",',
            '  "evidence": ["..."]',
            "}",
            "",
            "Malformed response:",
            text,
        ]
    )
    try:
        repaired_turn = provider.next_turn(
            system_prompt=(
                "You repair malformed autonomous evolution assessment payloads. "
                "Return one valid JSON object only."
            ),
            messages=[ChatMessage(role="user", text=prompt)],
            tool_schema=[],
        )
        repaired_text = str(repaired_turn.assistant_text or "").strip()
        repaired = _parse_assessment_payload(repaired_text)
        return repaired if isinstance(repaired, dict) else None
    except Exception:
        return None


def _repair_completion_payload(text: str, *, provider: BaseProvider) -> dict[str, Any] | None:
    prompt = "\n".join(
        [
            "The following task-completion judgment was supposed to be strict JSON but was malformed or inconsistent.",
            "Rewrite it as one valid JSON object only.",
            "Required fields:",
            "{",
            '  "completed": true|false,',
            '  "confidence": 0.0,',
            '  "reason": "short reason",',
            '  "evidence": ["1-4 short evidence strings"]',
            "}",
            "",
            "Malformed response:",
            text,
        ]
    )
    try:
        repaired_turn = provider.next_turn(
            system_prompt=(
                "You repair malformed task-completion payloads. "
                "Return one valid JSON object only."
            ),
            messages=[ChatMessage(role="user", text=prompt)],
            tool_schema=[],
        )
        repaired_text = str(repaired_turn.assistant_text or "").strip()
        repaired = _parse_completion_payload(repaired_text)
        return repaired if isinstance(repaired, dict) else None
    except Exception:
        return None


def _parse_json_object_candidate(candidate: str) -> dict[str, Any] | None:
    normalized = (
        str(candidate)
        .strip()
        .replace("\ufeff", "")
        .replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
    )
    if not normalized:
        return None
    try:
        payload = json.loads(normalized)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return payload

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", normalized):
        try:
            payload, end_index = decoder.raw_decode(normalized[match.start() :])
        except json.JSONDecodeError:
            continue
        trailing = normalized[match.start() + end_index :].strip()
        if trailing.startswith("```"):
            trailing = trailing[3:].strip()
        if trailing and not trailing.startswith((",", "]", "}")):
            # Ignore explanatory text that may follow a valid JSON object.
            pass
        if isinstance(payload, dict):
            return payload
    return None


def _normalize_capability_gap(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = _optional_text(raw.get("name"))
    if not name:
        return None
    preferred_surfaces = [str(item).strip() for item in raw.get("preferred_surfaces", []) if str(item).strip()]
    evidence = [str(item).strip() for item in raw.get("evidence", []) if str(item).strip()]
    normalized = {
        "name": name,
        "preferred_surfaces": preferred_surfaces,
        "evidence": evidence,
    }
    bundle_name = _optional_text(raw.get("bundle_name"))
    if bundle_name:
        normalized["bundle_name"] = bundle_name
    for key in ("inputs", "outputs", "workflow_actions", "state_targets", "dependencies", "constraints", "validation_targets", "domain_tags"):
        values = [str(item).strip() for item in raw.get(key, []) if str(item).strip()]
        if values:
            normalized[key] = values
    growth_units = [str(item).strip() for item in raw.get("growth_units", []) if str(item).strip()]
    if growth_units:
        normalized["growth_units"] = growth_units
    research_plan = raw.get("research_plan")
    if isinstance(research_plan, dict):
        compact_research_plan: dict[str, Any] = {}
        for key in ("search_queries", "implementation_checkpoints", "source_preferences", "selection_criteria"):
            values = [str(item).strip() for item in research_plan.get(key, []) if str(item).strip()]
            if values:
                compact_research_plan[key] = values
        if compact_research_plan:
            normalized["research_plan"] = compact_research_plan
    implementation_contract = _normalize_contract(raw.get("implementation_contract"))
    if implementation_contract:
        normalized["implementation_contract"] = implementation_contract
    replay_contract = _normalize_contract(raw.get("replay_contract"))
    if replay_contract:
        if "max_refinement_rounds" in replay_contract:
            try:
                replay_contract["max_refinement_rounds"] = max(0, int(replay_contract["max_refinement_rounds"]))
            except Exception:
                replay_contract.pop("max_refinement_rounds", None)
        normalized["replay_contract"] = replay_contract
    return normalized


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _coerce_confidence(value: Any) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except Exception:
        return 0.5


def _normalize_outcome(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {item.value for item in Outcome}:
        return normalized
    return Outcome.PARTIAL.value


def _resolve_existing_bundle_name(
    assessment: AutonomousEvolutionAssessment,
    *,
    provider: BaseProvider,
) -> str | None:
    capability_gap = assessment.capability_gap or {}
    catalog = ecosystem_bundle_catalog()
    if not catalog:
        return None
    prompt = "\n".join(
        [
            "Choose the best existing ecosystem bundle for this capability gap.",
            "Return JSON only with {\"bundle_name\": \"...\"} or {\"bundle_name\": \"\"}.",
            "Choose an existing bundle only when it is clearly a good fit.",
            "",
            "Capability gap:",
            json.dumps(capability_gap, ensure_ascii=False, indent=2),
            "",
            "Available bundles:",
            json.dumps(catalog, ensure_ascii=False, indent=2),
        ]
    )
    try:
        turn = provider.next_turn(
            system_prompt=(
                "You map capability gaps to existing self-evolution bundles. "
                "Only choose a bundle when the match is strong and specific."
            ),
            messages=[ChatMessage(role="user", text=prompt)],
            tool_schema=[],
        )
        payload = _parse_assessment_payload(str(turn.assistant_text or "").strip())
    except Exception:
        return None
    bundle_name = _optional_text(payload.get("bundle_name"))
    return bundle_name


def _compile_capability_gap(
    snapshot: dict[str, Any],
    *,
    runtime: HarnessRuntime,
    assessment: AutonomousEvolutionAssessment,
    provider: BaseProvider,
) -> None:
    if not assessment.needs_evolution or assessment.operator != "grow_ecosystem":
        return
    if assessment.capability_gap is None:
        return
    prompt = _build_capability_compiler_prompt(snapshot, runtime, assessment)
    compiled_payload: dict[str, Any] | None = None
    for index in range(2):
        active_provider = provider if index == 0 else _clone_provider(provider)
        try:
            turn = active_provider.next_turn(
                system_prompt=_CAPABILITY_COMPILER_SYSTEM_PROMPT,
                messages=[ChatMessage(role="user", text=prompt)],
                tool_schema=[],
            )
            parsed = _parse_assessment_payload(str(turn.assistant_text or "").strip())
            if isinstance(parsed, dict):
                compiled_payload = parsed
                break
        except Exception:
            continue
    if not isinstance(compiled_payload, dict):
        return
    compiled_gap = _normalize_capability_gap(compiled_payload.get("capability_gap"))
    if not compiled_gap:
        return
    merged_gap = dict(assessment.capability_gap)
    for key, value in compiled_gap.items():
        if isinstance(value, dict) and isinstance(merged_gap.get(key), dict):
            nested = dict(merged_gap.get(key, {}))
            nested.update(value)
            merged_gap[key] = nested
            continue
        merged_gap[key] = value
    assessment.capability_gap = merged_gap


def _build_capability_compiler_prompt(
    snapshot: dict[str, Any],
    runtime: HarnessRuntime,
    assessment: AutonomousEvolutionAssessment,
) -> str:
    messages = list(snapshot.get("messages", []))
    transcript_items: list[str] = []
    for message in messages[-16:]:
        role = str(message.get("role", ""))
        text = _normalize_text_for_ai(message.get("text", ""))
        if role in {"user", "assistant"} and text:
            transcript_items.append(f"{role}: {text[:600]}")
    tool_history = list(dict(snapshot.get("metadata", {})).get("tool_history", []))
    tool_lines = []
    for item in tool_history[-10:]:
        tool_name = str(item.get("tool_name", ""))
        result = dict(item.get("result", {}))
        status = "error" if result.get("is_error") else "ok"
        output = _normalize_text_for_ai(result.get("output", "")).replace("\n", " ")
        tool_lines.append(f"{tool_name} [{status}]: {output[:220]}")
    workspace_surface = _runtime_surface_summary(runtime, compact=False)
    return "\n".join(
        [
            "Compile one reusable capability spec from this finished session.",
            "The session already happened. Focus on what capability should be persisted after the fact.",
            "Prefer wrapping or extending the current workspace surface over pretending nothing already exists.",
            "",
            "Current assessment:",
            json.dumps(assessment.to_dict(), ensure_ascii=False, indent=2),
            "",
            "Current workspace surface:",
            json.dumps(workspace_surface, ensure_ascii=False, indent=2),
            "",
            "Recent transcript:",
            *transcript_items,
            "",
            "Recent tool evidence:",
            *tool_lines,
            "",
            "Return JSON with fields:",
            "{",
            '  "capability_gap": {',
            '    "name": "...",',
            '    "preferred_surfaces": ["plugin","mcp","skill","command","agent"],',
            '    "growth_units": ["plugin","mcp","skill","command","agent","bootstrap"],',
            '    "inputs": ["..."],',
            '    "outputs": ["..."],',
            '    "workflow_actions": ["..."],',
            '    "state_targets": ["..."],',
            '    "dependencies": ["..."],',
            '    "constraints": ["..."],',
            '    "validation_targets": ["..."],',
            '    "domain_tags": ["..."],',
            '    "research_plan": {',
            '      "search_queries": ["..."],',
            '      "implementation_checkpoints": ["..."],',
            '      "source_preferences": ["..."],',
            '      "selection_criteria": ["..."]',
            "    },",
            '    "implementation_contract": {',
            '      "surface_kind": "instructional|executable|mixed",',
            '      "summary": "...",',
            '      "primary_entrypoints": ["plugin","mcp","skill","command","agent"],',
            '      "runtime_dependencies": ["..."],',
            '      "concrete_operations": ["..."],',
            '      "state_artifacts": ["..."],',
            '      "deliverable_paths": ["..."],',
            '      "validation_steps": ["..."],',
            '      "notes": ["..."]',
            "    },",
            '    "replay_contract": {',
            '      "success_signals": ["..."],',
            '      "failure_signals": ["..."],',
            '      "validation_hints": ["..."],',
            '      "preferred_entrypoints": ["..."],',
            '      "max_refinement_rounds": 2',
            "    },",
            '    "evidence": ["..."]',
            "  }",
            "}",
            "The output should describe what should be persisted after the task, not how the user originally phrased it.",
            "Keep concrete tool and system names when they matter, such as kubectl, ffmpeg, Slack, or specific APIs.",
            "Use surface_kind=instructional when the durable value is mainly guidance, workflow instructions, or discoverability rather than a new execution engine.",
            "Use surface_kind=executable only when the task truly needs a newly persisted execution path beyond existing tools and surfaces.",
        ]
    )


def assess_task_completion_snapshot(
    snapshot: dict[str, Any],
    *,
    workspace: str | Path,
    settings,
    provider: BaseProvider | None = None,
) -> dict[str, Any]:
    completion_provider = _prepare_assessment_provider(provider or build_live_provider(settings=settings))
    prompt = _build_task_completion_prompt(snapshot, workspace=workspace)
    turn = completion_provider.next_turn(
        system_prompt=_TASK_COMPLETION_SYSTEM_PROMPT,
        messages=[ChatMessage(role="user", text=prompt)],
        tool_schema=[],
    )
    payload = _parse_completion_payload_with_repair(str(turn.assistant_text or "").strip(), provider=completion_provider)
    return {
        "completed": bool(payload.get("completed", False)),
        "confidence": _coerce_confidence(payload.get("confidence", 0.5)),
        "reason": str(payload.get("reason", "")).strip() or "No completion reason returned.",
        "evidence": [str(item).strip() for item in payload.get("evidence", []) if str(item).strip()],
        "mode": "ai",
    }


def _completion_assessment_with_ai_or_fallback(
    snapshot: dict[str, Any],
    *,
    workspace: str | Path,
    settings,
    provider: BaseProvider | None,
) -> dict[str, Any]:
    if bool(getattr(settings.runtime, "auto_self_evolution_require_task_completion", True)):
        active_provider = _clone_provider(provider) if provider is not None else None
        try:
            return assess_task_completion_snapshot(
                snapshot,
                workspace=workspace,
                settings=settings,
                provider=active_provider,
            )
        except Exception:
            return {
                "completed": False,
                "confidence": 0.0,
                "reason": "AI task-completion assessment was unavailable or failed, so automatic self-evolution was skipped conservatively.",
                "evidence": [],
                "mode": "ai_unavailable",
            }
    return {
        "completed": True,
        "confidence": 1.0,
        "reason": "Task-completion gating is disabled in runtime settings.",
        "evidence": [],
        "mode": "disabled",
    }


def _build_task_completion_prompt(
    snapshot: dict[str, Any],
    *,
    workspace: str | Path,
) -> str:
    runtime = HarnessRuntime(workspace)
    metadata = dict(snapshot.get("metadata", {}))
    query_stats = dict(metadata.get("query_stats", {}))
    messages = list(snapshot.get("messages", []))
    transcript_items: list[str] = []
    for message in messages[-10:]:
        role = str(message.get("role", "")).strip()
        text = _normalize_text_for_ai(message.get("text", ""))
        if role in {"user", "assistant"} and text:
            transcript_items.append(f"- {role}: {text[:360]}")
    tool_lines = _important_tool_evidence(snapshot, max_items=6, text_limit=220)
    required_outputs = _expected_output_paths_from_snapshot(snapshot)
    missing_outputs = _missing_expected_outputs(required_outputs, workspace=workspace)
    return "\n".join(
        [
            "Decide whether the user task was truly completed in this session.",
            "",
            "Task summary:",
            _task_summary(snapshot),
            "",
            "Session facts:",
            f"- stop_reason: {metadata.get('stop_reason')}",
            f"- turn_count: {metadata.get('turn_count')}",
            f"- total_tool_calls: {query_stats.get('total_tool_calls')}",
            f"- tool_failures: {query_stats.get('tool_failures')}",
            "",
            "Expected outputs mentioned by the user:",
            *([f"- {item}" for item in required_outputs] or ["- (no explicit output file paths mentioned)"]),
            "",
            "Currently missing expected outputs:",
            *([f"- {item}" for item in missing_outputs] or ["- (none)"]),
            "",
            "Workspace surface summary:",
            _compact_surface_summary(runtime),
            "",
            "Recent transcript summary:",
            *transcript_items,
            "",
            "Important tool evidence:",
            *tool_lines,
            "",
            "Return JSON only.",
        ]
    )


def _runtime_surface_summary(runtime: HarnessRuntime, *, compact: bool) -> dict[str, Any]:
    surface = runtime.discovery_surface(compact=compact)
    counts = dict(surface.get("counts", {}))
    return {
        "tool_count": counts.get("tools", 0),
        "command_count": counts.get("commands", 0),
        "skill_count": counts.get("skills", 0),
        "agent_count": counts.get("agents", 0),
        "plugin_count": counts.get("plugins", 0),
        "mcp_server_count": counts.get("mcp_servers", 0),
        "mcp_tool_count": counts.get("mcp_tools", 0),
        "mcp_prompt_count": counts.get("mcp_prompts", 0),
        "tools": list(surface.get("tools", [])),
        "commands": list(surface.get("commands", [])),
        "skills": list(surface.get("skills", [])),
        "agents": list(surface.get("agents", [])),
        "plugins": list(surface.get("plugins", [])),
        "mcp_servers": list(surface.get("mcp_servers", [])),
        "mcp_tools": list(surface.get("mcp_tools", [])),
        "mcp_prompts": list(surface.get("mcp_prompts", [])),
    }


def _normalize_contract(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key, value in raw.items():
        normalized_key = str(key).strip()
        if not normalized_key:
            continue
        if isinstance(value, dict):
            nested = _normalize_contract(value)
            if nested:
                normalized[normalized_key] = nested
            continue
        if isinstance(value, list):
            items = [str(item).strip() for item in value if str(item).strip()]
            if items:
                normalized[normalized_key] = items
            continue
        if isinstance(value, bool):
            normalized[normalized_key] = value
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            normalized[normalized_key] = value
            continue
        text = str(value).strip()
        if text:
            normalized[normalized_key] = text
    return normalized


def _autonomous_trigger_decision(
    snapshot: dict[str, Any],
    *,
    workspace: str | Path | None = None,
    settings,
    completion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(snapshot.get("metadata", {}))
    query_stats = dict(metadata.get("query_stats", {}))
    active_command = dict(metadata.get("active_command") or {})
    stop_reason = str(metadata.get("stop_reason", "") or "").strip()
    signals: list[str] = []
    total_tool_calls = int(query_stats.get("total_tool_calls", 0) or 0)
    if total_tool_calls > 0:
        signals.append(f"tool_calls:{total_tool_calls}")
    tool_failures = int(query_stats.get("tool_failures", 0) or 0)
    if tool_failures > 0:
        signals.append(f"tool_failures:{tool_failures}")
    mutating_tool_calls = int(query_stats.get("mutating_tool_calls", 0) or 0)
    if mutating_tool_calls > 0:
        signals.append(f"mutating_tool_calls:{mutating_tool_calls}")
    if int(query_stats.get("context_truncations", 0) or 0) > 0 or int(query_stats.get("context_compactions", 0) or 0) > 0:
        signals.append("context_pressure")
    if active_command.get("name"):
        signals.append(f"active_command:{active_command.get('name')}")
    if stop_reason in {
        "max_consecutive_tool_rounds",
        "max_empty_assistant_turns",
        "repeated_tool_signature",
        "max_total_tool_calls",
        "tool_calls",
        "max_repeated_assistant_turns",
    }:
        signals.append(f"stop_reason:{stop_reason}")
    completion = dict(
        completion
        or {
            "completed": False,
            "confidence": 0.0,
            "reason": "No AI task-completion assessment was supplied.",
            "evidence": [],
            "mode": "unspecified",
        }
    )
    require_runtime_signals = bool(getattr(settings.runtime, "auto_self_evolution_require_runtime_signals", True))
    require_task_completion = bool(getattr(settings.runtime, "auto_self_evolution_require_task_completion", True))
    attempted = bool(completion.get("completed", False)) if require_task_completion else bool(signals)
    if not require_runtime_signals and not require_task_completion:
        attempted = True
    if require_task_completion and not completion["completed"]:
        return {
            "attempt": False,
            "signals": signals,
            "task_completion": completion,
            "reason": (
                "Skipped autonomous self-evolution because the user task does not look complete yet. "
                + str(completion["reason"])
            ),
        }
    return {
        "attempt": attempted,
        "signals": signals,
        "task_completion": completion,
        "reason": (
            "Autonomous self-evolution starts only after the user task appears complete and the session produced "
            "runtime signals such as tool usage, command pressure, context pressure, or abnormal stop reasons."
            if attempted
            else "Skipped autonomous self-evolution because the session did not produce meaningful runtime signals."
        ),
    }


def _task_completion_assessment_disabled(snapshot: dict[str, Any], *, workspace: str | Path | None = None) -> dict[str, Any]:
    metadata = dict(snapshot.get("metadata", {}))
    stop_reason = str(metadata.get("stop_reason", "") or "").strip()
    messages = list(snapshot.get("messages", []))
    last_assistant = ""
    for message in reversed(messages):
        if str(message.get("role", "")) == "assistant" and str(message.get("text", "")).strip():
            last_assistant = str(message.get("text", "")).strip().lower()
            break
    tool_history = list(metadata.get("tool_history", []))
    tool_outputs = "\n".join(
        str(dict(item.get("result", {})).get("output", "")).strip().lower()
        for item in tool_history
    )
    success_markers = (
        "successfully",
        "success",
        "completed",
        "done",
        "generated",
        "saved",
        "created",
        "written to",
        "report saved",
        "check completed",
        "analysis complete",
        "任务完成",
        "已经完成",
        "完成了",
        "完成检查",
        "检查完成",
        "已完成",
        "已生成",
        "已保存",
        "已创建",
        "报告已保存",
        "结果已保存",
        "检查结果摘要",
        "发现异常",
    )
    failure_markers = (
        "failed",
        "failure",
        "error",
        "traceback",
        "not recognized",
        "not found",
        "missing",
        "could not",
        "unable to",
        "need to fix",
        "need to inspect again",
        "script failed",
        "keyerror",
        "unfinished",
        "未完成",
        "失败",
        "报错",
        "无法",
        "需要修复",
        "需要继续",
        "还没完成",
        "还需要",
    )
    tool_artifact_markers = (
        "wrote ",
        "saved ",
        "created ",
        "generated ",
        "written to",
        "saved to",
        "report saved",
    )
    assistant_artifact_markers = (
        "saved to",
        "written to",
        "report saved",
        "results saved",
        "报告已保存",
        "结果已保存",
        "已写入",
        "已输出到",
        "保存路径",
    )
    explicit_success = bool(last_assistant and any(marker in last_assistant for marker in success_markers))
    explicit_failure = bool(last_assistant and any(marker in last_assistant for marker in failure_markers))
    artifact_evidence = any(marker in tool_outputs for marker in tool_artifact_markers) or any(
        marker in last_assistant for marker in assistant_artifact_markers
    )
    required_outputs = _expected_output_paths_from_snapshot(snapshot)
    missing_outputs = _missing_expected_outputs(required_outputs, workspace=workspace)
    abnormal_stop = stop_reason in {
        "max_consecutive_tool_rounds",
        "max_empty_assistant_turns",
        "repeated_tool_signature",
        "max_total_tool_calls",
        "tool_calls",
        "max_repeated_assistant_turns",
    }
    if explicit_failure and not explicit_success:
        return {
            "completed": False,
            "reason": "The final assistant turn still looked like a failure or unfinished state.",
            "last_assistant": last_assistant[:240],
            "stop_reason": stop_reason,
            "required_outputs": required_outputs,
            "missing_outputs": missing_outputs,
        }
    if explicit_success and missing_outputs:
        return {
            "completed": False,
            "reason": "The assistant claimed completion, but expected output files were still missing.",
            "last_assistant": last_assistant[:240],
            "stop_reason": stop_reason,
            "required_outputs": required_outputs,
            "missing_outputs": missing_outputs,
        }
    if abnormal_stop and not explicit_success and not artifact_evidence:
        return {
            "completed": False,
            "reason": "The session stopped abnormally before showing a clear completion signal.",
            "last_assistant": last_assistant[:240],
            "stop_reason": stop_reason,
            "required_outputs": required_outputs,
            "missing_outputs": missing_outputs,
        }
    if explicit_success or artifact_evidence:
        return {
            "completed": not bool(missing_outputs),
            "reason": (
                "The session showed explicit completion language or concrete output-artifact evidence."
                if not missing_outputs
                else "The session showed some output evidence, but required deliverables are still missing."
            ),
            "last_assistant": last_assistant[:240],
            "stop_reason": stop_reason,
            "required_outputs": required_outputs,
            "missing_outputs": missing_outputs,
        }
    return {
        "completed": False,
        "reason": "The session ended without a clear completion signal for the user task.",
        "last_assistant": last_assistant[:240],
        "stop_reason": stop_reason,
        "required_outputs": required_outputs,
        "missing_outputs": missing_outputs,
    }


def _task_completion_assessment(snapshot: dict[str, Any], *, workspace: str | Path | None = None) -> dict[str, Any]:
    del snapshot, workspace
    return {
        "completed": False,
        "confidence": 0.0,
        "reason": "Heuristic task-completion detection has been disabled; completion must come from AI judgment.",
        "evidence": [],
        "mode": "heuristic_disabled",
    }


def _normalize_text_for_ai(value: Any) -> str:
    text = str(value or "").replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    return text


def _expected_output_paths_from_snapshot(snapshot: dict[str, Any]) -> list[str]:
    messages = list(snapshot.get("messages", []))
    first_user = ""
    for message in messages:
        if str(message.get("role", "")) == "user" and str(message.get("text", "")).strip():
            first_user = str(message.get("text", "")).strip()
            break
    if not first_user:
        return []
    candidates = re.findall(
        r"[\w./\\\\:-]+\.(?:md|json|docx|doc|txt|csv|yaml|yml|xml|html|pdf|png|jpg|jpeg)",
        first_user,
        flags=re.IGNORECASE,
    )
    outputs: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = str(candidate).strip().strip("`'\"")
        lowered = normalized.lower()
        if not normalized:
            continue
        if lowered.endswith("manifest.json"):
            continue
        if "output" not in lowered and "report" not in lowered and "result" not in lowered:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        outputs.append(normalized)
    return outputs


def _missing_expected_outputs(paths: list[str], *, workspace: str | Path | None) -> list[str]:
    if workspace is None:
        return []
    root = Path(workspace).resolve()
    missing: list[str] = []
    for item in paths:
        candidate = Path(item)
        target = candidate if candidate.is_absolute() else (root / candidate).resolve()
        if not target.exists():
            missing.append(item)
    return missing


def _write_learning_fallbacks(
    workspace_root: Path,
    *,
    snapshot: dict[str, Any],
    assessment: AutonomousEvolutionAssessment,
    plan,
    execution,
    settings=None,
    completion: dict[str, Any] | None = None,
) -> dict[str, str]:
    promotion_state = str(getattr(execution, "promotion_state", "") or "").strip().lower()
    if promotion_state not in {"rejected", "blocked", "candidate_only"}:
        return {}
    if not bool(getattr(settings.runtime, "auto_self_evolution_apply_fallback_on_completed_tasks", True) if settings is not None else True):
        return {}
    if not _session_shows_successful_task_completion(completion=completion):
        return {}
    if list(getattr(execution, "applied_paths", []) or []):
        return {}

    memory_path = _apply_learning_memory_entry(workspace_root, snapshot=snapshot, assessment=assessment, plan=plan)
    skill_path = _materialize_learning_skill(workspace_root, snapshot=snapshot, assessment=assessment, plan=plan)
    artifacts: dict[str, str] = {}
    if memory_path is not None:
        artifacts["memory_applied_path"] = str(memory_path)
    if skill_path is not None:
        if skill_path.suffix == ".md" and ".evo-harness\\candidates\\" not in str(skill_path):
            artifacts["skill_applied_path"] = str(skill_path)
        else:
            artifacts["skill_candidate_path"] = str(skill_path)
    return artifacts


def _write_failure_learning_artifacts(
    workspace_root: Path,
    *,
    snapshot: dict[str, Any],
    reason: str,
    error: str | None = None,
    completion: dict[str, Any] | None = None,
) -> dict[str, str]:
    if not _should_materialize_failure_learning(snapshot, completion=completion, error=error):
        return {}

    memory_path = _apply_failure_memory_entry(
        workspace_root,
        snapshot=snapshot,
        reason=reason,
        error=error,
        completion=completion,
    )
    skill_path = _apply_failure_recovery_skill(
        workspace_root,
        snapshot=snapshot,
        reason=reason,
        error=error,
        completion=completion,
    )
    artifacts: dict[str, str] = {}
    if memory_path is not None:
        artifacts["failure_memory_applied_path"] = str(memory_path)
    if skill_path is not None:
        artifacts["failure_skill_applied_path"] = str(skill_path)
    return artifacts


def _run_failure_recovery_session(
    workspace_root: Path,
    *,
    snapshot: dict[str, Any],
    settings,
    provider: BaseProvider | None,
    failure_artifacts: dict[str, str],
    completion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings.runtime, "auto_failure_recovery_on_incomplete", False)):
        return {}
    if not failure_artifacts:
        return {}

    original_prompt = _first_user_prompt_from_snapshot(list(snapshot.get("messages", []))).strip()
    if not original_prompt:
        return {"status": "skipped", "reason": "No original user prompt was available for automatic recovery."}

    active_provider = _clone_provider(provider) if provider is not None else None
    if active_provider is None:
        try:
            active_provider = build_live_provider(settings=settings)
        except Exception as exc:
            return {"status": "skipped", "reason": f"Could not start recovery provider: {exc}"}

    from evo_harness.harness.conversation import ConversationEngine

    recovery_runtime = HarnessRuntime(workspace_root)
    recovery_runtime.settings.runtime.auto_self_evolution = False
    if hasattr(recovery_runtime.settings.runtime, "auto_failure_recovery_on_incomplete"):
        recovery_runtime.settings.runtime.auto_failure_recovery_on_incomplete = False
    max_turns = max(1, int(getattr(settings.runtime, "auto_failure_recovery_max_turns", 4) or 4))
    recovery_prompt = _build_failure_recovery_prompt(
        snapshot,
        completion=completion,
        failure_artifacts=failure_artifacts,
    )
    result = ConversationEngine(recovery_runtime).submit(
        prompt=recovery_prompt,
        provider=active_provider,
        max_turns=max_turns,
    )
    recovery_snapshot = load_session_snapshot(workspace_root, session_id="latest") or {}
    recovery_completion = _task_completion_assessment_disabled(recovery_snapshot, workspace=workspace_root)
    return {
        "status": "completed" if recovery_completion.get("completed") else "incomplete",
        "completed": bool(recovery_completion.get("completed")),
        "reason": str(recovery_completion.get("reason", "") or ""),
        "stop_reason": result.stop_reason,
        "turn_count": result.turn_count,
        "tool_calls": result.query_stats.get("total_tool_calls"),
        "session_path": result.session_path,
        "assistant_preview": _last_assistant_text(recovery_snapshot)[:280],
        "failure_artifacts": dict(failure_artifacts),
    }


def _build_failure_recovery_prompt(
    snapshot: dict[str, Any],
    *,
    completion: dict[str, Any] | None,
    failure_artifacts: dict[str, str],
) -> str:
    original_prompt = _first_user_prompt_from_snapshot(list(snapshot.get("messages", []))).strip()
    completion_payload = dict(completion or {})
    reason = str(completion_payload.get("reason", "") or "").strip()
    missing_outputs = [str(item).strip() for item in completion_payload.get("missing_outputs", []) if str(item).strip()]
    lines = [
        "Retry the original user task in an autonomous recovery session.",
        "Do not wait for another user turn.",
        "Before answering, inspect any new recovery memories and recovery skills already materialized in the workspace.",
        "Use multiple turns if needed, and prefer real deliverables over commentary.",
        "",
        f"Original task: {original_prompt}",
    ]
    if reason:
        lines.append(f"Previous failure summary: {reason}")
    if missing_outputs:
        lines.append("Missing expected outputs: " + ", ".join(missing_outputs))
    if failure_artifacts.get("failure_skill_applied_path"):
        lines.append(f"Recovery skill path: {failure_artifacts['failure_skill_applied_path']}")
    if failure_artifacts.get("failure_memory_applied_path"):
        lines.append(f"Recovery memory path: {failure_artifacts['failure_memory_applied_path']}")
    lines.extend(
        [
            "",
            "Recovery checklist:",
            "1. Read the relevant memory and recovery skill first.",
            "2. Check whether an existing command, skill, plugin, or MCP surface already solves the task.",
            "3. Produce the missing deliverable if possible.",
            "4. If still blocked, end with a concise blocker report tied to the concrete missing asset or dependency.",
        ]
    )
    return "\n".join(lines).strip()


def _should_materialize_failure_learning(
    snapshot: dict[str, Any],
    *,
    completion: dict[str, Any] | None = None,
    error: str | None = None,
) -> bool:
    completion_payload = dict(completion or {})
    if completion_payload.get("completed") is True:
        return False
    if str(error or "").strip():
        return True
    completion_reason = str(completion_payload.get("reason", "") or "").strip().lower()
    missing_outputs = list(completion_payload.get("missing_outputs", []) or [])
    if missing_outputs:
        return True
    if completion_reason and any(
        marker in completion_reason
        for marker in (
            "missing",
            "unfinished",
            "not complete",
            "does not look complete",
            "failed",
            "failure",
            "deliverables are still missing",
            "without a clear completion signal",
            "需要修复",
            "未完成",
            "失败",
            "缺少",
        )
    ):
        return True

    metadata = dict(snapshot.get("metadata", {}))
    query_stats = dict(metadata.get("query_stats", {}))
    if int(query_stats.get("tool_failures", 0) or 0) > 0:
        return True
    if int(query_stats.get("mutating_tool_failures", 0) or 0) > 0:
        return True

    stop_reason = str(metadata.get("stop_reason", "") or "").strip()
    if stop_reason in {
        "max_consecutive_tool_rounds",
        "max_empty_assistant_turns",
        "repeated_tool_signature",
        "max_total_tool_calls",
        "max_tool_failures",
        "max_mutating_tool_failures",
        "tool_calls",
        "max_repeated_assistant_turns",
    }:
        return True

    for item in list(metadata.get("tool_history", [])):
        if dict(item.get("result", {})).get("is_error"):
            return True

    last_assistant = _last_assistant_text(snapshot).lower()
    failure_markers = (
        "failed",
        "failure",
        "error",
        "traceback",
        "not recognized",
        "not found",
        "missing",
        "could not",
        "unable to",
        "need to fix",
        "unfinished",
        "失败",
        "报错",
        "无法",
        "未完成",
        "还需要",
    )
    return bool(last_assistant and any(marker in last_assistant for marker in failure_markers))


def _apply_failure_memory_entry(
    workspace_root: Path,
    *,
    snapshot: dict[str, Any],
    reason: str,
    error: str | None = None,
    completion: dict[str, Any] | None = None,
) -> Path:
    task_id = _snapshot_learning_id(snapshot)
    title = f"Failure recovery from {task_id}"
    first_prompt = _first_user_prompt_from_snapshot(list(snapshot.get("messages", [])))
    metadata = dict(snapshot.get("metadata", {}))
    query_stats = dict(metadata.get("query_stats", {}))
    stop_reason = str(metadata.get("stop_reason", "") or "unknown")
    failure_evidence = _failure_evidence_lines(snapshot, reason=reason, error=error, completion=completion)
    body = "\n".join(
        [
            f"# {title}",
            "",
            f"- When to use: A future task resembles `{first_prompt[:160] or 'this failed session'}`.",
            "- Failure type: unfinished or failed user task, not a promoted capability.",
            f"- Stop reason: `{stop_reason}`",
            f"- Tool calls: {query_stats.get('total_tool_calls', 0)}",
            f"- Tool failures: {query_stats.get('tool_failures', 0)}",
            "- Reuse goal: recover faster next time by starting from the known failure signals instead of rediscovering them.",
            "",
            "## Failure Evidence",
            *(f"- {item}" for item in failure_evidence),
            "",
            "## Recovery First Steps",
            "- Start by checking whether a matching command, skill, plugin, MCP tool, or memory already exists.",
            "- Reproduce the smallest failing step before attempting a broad rewrite.",
            "- Verify the concrete deliverable exists before claiming completion.",
            "- If the same failure appears again, prefer turning this recovery path into a durable command, skill, or plugin.",
            "",
        ]
    ).strip() + "\n"
    return add_memory_entry(workspace_root, title, body)


def _apply_failure_recovery_skill(
    workspace_root: Path,
    *,
    snapshot: dict[str, Any],
    reason: str,
    error: str | None = None,
    completion: dict[str, Any] | None = None,
) -> Path:
    first_prompt = _first_user_prompt_from_snapshot(list(snapshot.get("messages", [])))
    slug_source = first_prompt or reason or error or _snapshot_learning_id(snapshot)
    slug = _slugify(slug_source)[:80]
    if not slug.endswith("recovery"):
        slug = f"{slug}-recovery"
    name = f"{slug}-playbook"
    skill_dir = workspace_root / ".claude" / "skills"
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / f"{name}.md"
    failure_evidence = _failure_evidence_lines(snapshot, reason=reason, error=error, completion=completion)
    task_id = _snapshot_learning_id(snapshot)
    body = "\n".join(
        [
            "---",
            f"name: {name}",
            f"description: Recover from failed or unfinished sessions like {task_id} before retrying the full task.",
            "---",
            "",
            f"# {name}",
            "",
            f"Use this when a task resembles: `{first_prompt[:180] or 'the failed session that created this playbook'}`",
            "",
            "## Known Failure Signals",
            *(f"- {item}" for item in failure_evidence),
            "",
            "## Recovery Workflow",
            "- Load relevant memories before planning a new attempt.",
            "- Inspect the live registry for existing commands, skills, plugins, agents, and MCP tools before writing new code.",
            "- Re-run or simulate only the smallest failing step first.",
            "- Prefer a concrete artifact check over a prose-only success claim.",
            "- If recovery succeeds twice, promote the pattern into a dedicated command/plugin/tool surface.",
            "",
            "## Stop Conditions",
            "- Stop and record the blocker if required credentials, files, or external services are missing.",
            "- Stop and request a durable capability if the same workflow still depends on ad-hoc one-off commands.",
            "",
        ]
    ).strip() + "\n"
    path.write_text(body, encoding="utf-8")
    return path


def _failure_evidence_lines(
    snapshot: dict[str, Any],
    *,
    reason: str,
    error: str | None = None,
    completion: dict[str, Any] | None = None,
) -> list[str]:
    evidence: list[str] = []
    reason_text = str(reason or "").strip()
    if reason_text:
        evidence.append(f"Reason: {reason_text[:260]}")
    if error and str(error).strip():
        evidence.append(f"Autonomous evolution error: {str(error).strip()[:260]}")
    completion_payload = dict(completion or {})
    completion_reason = str(completion_payload.get("reason", "") or "").strip()
    if completion_reason:
        evidence.append(f"Task completion gate: {completion_reason[:260]}")
    for item in completion_payload.get("evidence", []) or []:
        text = str(item).strip()
        if text:
            evidence.append(f"Completion evidence: {text[:220]}")

    metadata = dict(snapshot.get("metadata", {}))
    stop_reason = str(metadata.get("stop_reason", "") or "").strip()
    if stop_reason:
        evidence.append(f"Stop reason: {stop_reason}")
    query_stats = dict(metadata.get("query_stats", {}))
    if query_stats:
        evidence.append(
            "Query stats: "
            f"tool_calls={query_stats.get('total_tool_calls', 0)}, "
            f"tool_failures={query_stats.get('tool_failures', 0)}, "
            f"mutating_tool_failures={query_stats.get('mutating_tool_failures', 0)}"
        )
    for item in list(metadata.get("tool_history", []))[-6:]:
        result = dict(item.get("result", {}))
        if not result.get("is_error"):
            continue
        tool_name = str(item.get("tool_name", "unknown"))
        output = str(result.get("output", "") or "").strip().replace("\n", " ")
        evidence.append(f"Tool failure from `{tool_name}`: {output[:260] or 'error without output'}")
    last_assistant = _last_assistant_text(snapshot)
    if last_assistant:
        evidence.append(f"Last assistant turn: {last_assistant[:260]}")
    return _unique_failure_evidence(evidence)[:12] or ["The session failed or remained unfinished, but no compact evidence was available."]


def _unique_failure_evidence(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def _last_assistant_text(snapshot: dict[str, Any]) -> str:
    for message in reversed(list(snapshot.get("messages", []))):
        if str(message.get("role", "")) == "assistant" and str(message.get("text", "")).strip():
            return str(message.get("text", "")).strip()
    return ""


def _snapshot_learning_id(snapshot: dict[str, Any]) -> str:
    for key in ("archive_session_id", "session_id"):
        value = str(snapshot.get(key, "") or "").strip()
        if value and value != "latest":
            return value
    return "latest"


def _session_shows_successful_task_completion_legacy(snapshot: dict[str, Any]) -> bool:
    messages = list(snapshot.get("messages", []))
    recent_assistant = [str(message.get("text", "")).strip().lower() for message in messages if str(message.get("role", "")) == "assistant"]
    success_markers = (
        "成功",
        "完成",
        "已生成",
        "generated",
        "created",
        "saved",
        "done",
        "completed",
        "found ffmpeg",
        "找到 ffmpeg",
    )
    return any(any(marker in text for marker in success_markers) for text in recent_assistant if text)


def _session_shows_successful_task_completion_legacy_2(snapshot: dict[str, Any]) -> bool:
    messages = list(snapshot.get("messages", []))
    recent_assistant = [
        str(message.get("text", "")).strip().lower()
        for message in messages
        if str(message.get("role", "")) == "assistant"
    ]
    success_markers = (
        "成功",
        "完成",
        "已生成",
        "已保存",
        "已创建",
        "generated",
        "created",
        "saved",
        "done",
        "completed",
        "found ffmpeg",
        "找到 ffmpeg",
    )
    return any(any(marker in text for marker in success_markers) for text in recent_assistant if text)


def _session_shows_successful_task_completion(
    *,
    completion: dict[str, Any] | None = None,
) -> bool:
    return bool(dict(completion or {}).get("completed"))


def _apply_learning_memory_entry(
    workspace_root: Path,
    *,
    snapshot: dict[str, Any],
    assessment: AutonomousEvolutionAssessment,
    plan,
) -> Path | None:
    task_id = str(snapshot.get("session_id", "latest"))
    evidence = [str(item).strip() for item in (assessment.evidence or []) if str(item).strip()][:4]
    gap = dict(assessment.capability_gap or {})
    dependencies = [str(item).strip() for item in gap.get("dependencies", []) if str(item).strip()][:5]
    workflow = [str(item).strip() for item in gap.get("workflow_actions", []) if str(item).strip()][:5]
    outputs = [str(item).strip() for item in gap.get("outputs", []) if str(item).strip()][:5]
    constraints = [str(item).strip() for item in gap.get("constraints", []) if str(item).strip()][:4]
    title = f"Lesson from {task_id}"
    body = "\n".join(
        [
            f"# {title}",
            "",
            f"- When to use: Repeat tasks similar to `{_first_user_prompt_from_snapshot(list(snapshot.get('messages', [])))[:120]}`.",
            f"- Pattern: {assessment.summary or plan.trace.summary}",
            f"- Avoid: Do not rediscover external tools or rebuild one-off scripts from scratch if the same capability gap has already been seen.",
            "",
            "## Task Shape",
            f"- Capability gap: {gap.get('name', 'unknown')}",
            *(f"- Output target: {item}" for item in outputs),
            *(f"- Workflow action: {item}" for item in workflow),
            *(f"- Dependency: {item}" for item in dependencies),
            *(f"- Constraint: {item}" for item in constraints),
            "",
            "## Key Evidence",
            *(f"- {item}" for item in evidence),
            "",
            "## Next Best Reuse Path",
            f"- Preferred operator observed: `{assessment.operator}`",
            f"- Preferred bundle: `{assessment.bundle_name or plan.change_request.get('bundle_name', '') or 'none'}`",
            "",
            "## Why this was saved",
            "- The original task appears completed, but replay/promotion did not pass.",
            "- Preserve the successful workaround so the next iteration can productize it instead of rediscovering it.",
            "",
        ]
    ).strip() + "\n"
    return add_memory_entry(workspace_root, title, body)


def _write_learning_skill_candidate(
    workspace_root: Path,
    *,
    snapshot: dict[str, Any],
    assessment: AutonomousEvolutionAssessment,
    plan,
) -> Path | None:
    candidate_dir = workspace_root / ".evo-harness" / "candidates" / "skills"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    task_id = str(snapshot.get("session_id", "latest"))
    slug = _slugify(assessment.capability_gap.get("name") if assessment.capability_gap else "successful-workaround")
    path = candidate_dir / f"{slug}-playbook.candidate.md"
    task_text = _first_user_prompt_from_snapshot(list(snapshot.get("messages", [])))
    evidence = [str(item).strip() for item in (assessment.evidence or []) if str(item).strip()][:4]
    steps = _skill_steps_from_assessment(assessment)
    body = "\n".join(
        [
            f"---",
            f"name: {slug}-playbook",
            f"description: Reuse the successful workaround from session {task_id} before rebuilding the whole capability from scratch.",
            f"---",
            "",
            f"# {slug} Playbook",
            "",
            f"Use this when a task resembles: `{task_text[:160]}`",
            "",
            "## Reuse Steps",
            *(f"- {step}" for step in steps),
            "",
            "## Evidence from the successful run",
            *(f"- {item}" for item in evidence),
            "",
            "## Goal",
            "- Reuse the known-good path first, then productize it into a durable plugin/command/skill surface.",
            "",
        ]
    ).strip() + "\n"
    path.write_text(body, encoding="utf-8")
    return path


def _apply_learning_skill(
    workspace_root: Path,
    *,
    snapshot: dict[str, Any],
    assessment: AutonomousEvolutionAssessment,
) -> Path:
    skill_dir = workspace_root / ".claude" / "skills"
    skill_dir.mkdir(parents=True, exist_ok=True)
    slug = _slugify(assessment.capability_gap.get("name") if assessment.capability_gap else "successful-workaround")
    path = skill_dir / f"{slug}-playbook.md"
    task_text = _first_user_prompt_from_snapshot(list(snapshot.get("messages", [])))
    evidence = [str(item).strip() for item in (assessment.evidence or []) if str(item).strip()][:4]
    steps = _skill_steps_from_assessment(assessment)
    content = "\n".join(
        [
            "---",
            f"name: {slug}-playbook",
            f"description: Reuse the successful workaround from session {snapshot.get('session_id', 'latest')} before rebuilding the whole capability from scratch.",
            "---",
            "",
            f"# {slug} Playbook",
            "",
            f"Use this when a task resembles: `{task_text[:160]}`",
            "",
            "## Reuse Steps",
            *(f"- {step}" for step in steps),
            "",
            "## Evidence from the successful run",
            *(f"- {item}" for item in evidence),
            "",
            "## Goal",
            "- Reuse the known-good path first, then productize it into a durable command/plugin/tool surface.",
            "",
        ]
    ).strip() + "\n"
    path.write_text(content, encoding="utf-8")
    return path


def _materialize_learning_skill(
    workspace_root: Path,
    *,
    snapshot: dict[str, Any],
    assessment: AutonomousEvolutionAssessment,
    plan,
) -> Path | None:
    del plan
    return _apply_learning_skill(workspace_root, snapshot=snapshot, assessment=assessment)


def _skill_steps_from_assessment(assessment: AutonomousEvolutionAssessment) -> list[str]:
    gap = dict(assessment.capability_gap or {})
    dependencies = [str(item).strip() for item in gap.get("dependencies", []) if str(item).strip()]
    constraints = [str(item).strip() for item in gap.get("constraints", []) if str(item).strip()]
    workflow = [str(item).strip() for item in gap.get("workflow_actions", []) if str(item).strip()]
    steps = [
        "Start from the compact summary of the previous successful run rather than the full raw transcript.",
        "Check whether the required external dependencies are already available before retrying the task.",
    ]
    if dependencies:
        steps.append("Verify dependencies: " + ", ".join(dependencies[:4]) + ".")
    if workflow:
        steps.append("Follow this workflow order: " + " -> ".join(workflow[:5]) + ".")
    if constraints:
        steps.append("Watch for known constraints: " + ", ".join(constraints[:3]) + ".")
    steps.append("If the task succeeds again, turn the workaround into a durable workflow instead of another one-off script.")
    return steps


def _slugify(value: Any) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return text or "successful-workaround"


def _first_user_prompt_from_snapshot(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        if str(message.get("role", "")) == "user" and str(message.get("text", "")).strip():
            return str(message.get("text", "")).strip()
    return ""


def _clone_provider(provider: BaseProvider) -> BaseProvider:
    try:
        return provider.clone()
    except Exception:
        return provider


def _write_autonomous_record(workspace: Path, record: dict[str, Any]) -> Path:
    record_dir = workspace / ".evo-harness" / "autonomous"
    record_dir.mkdir(parents=True, exist_ok=True)
    path = record_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_autonomous_failure_record(
    workspace: str | Path,
    *,
    session_id: str,
    error: str,
) -> Path:
    workspace_root = Path(workspace).resolve()
    snapshot = load_session_snapshot(workspace_root, session_id=session_id)
    record = {
        "workspace": str(workspace_root),
        "session_id": session_id,
        "status": "failed",
        "error": str(error).strip(),
    }
    if snapshot is not None:
        artifacts = _write_failure_learning_artifacts(
            workspace_root,
            snapshot=snapshot,
            reason="Autonomous self-evolution failed before it could finish its normal control loop.",
            error=error,
            completion={"completed": False, "reason": "Autonomous self-evolution raised an exception.", "evidence": [], "mode": "failure_record"},
        )
        if artifacts:
            record["failure_learning_artifacts"] = artifacts
    return _write_autonomous_record(workspace_root, record)
