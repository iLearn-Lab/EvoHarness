from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from evo_harness.harness.agents import AgentDefinition
from evo_harness.harness.provider import BaseProvider
from evo_harness.harness.query import run_query
from evo_harness.harness.runtime import HarnessRuntime


@dataclass(slots=True)
class SubagentResult:
    agent_name: str
    provider_name: str
    session_path: str
    message_count: int
    tool_count: int
    tool_names: list[str]
    summary: str
    stop_reason: str | None = None
    turn_count: int = 0
    model_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_subagent(
    runtime: HarnessRuntime,
    *,
    agent: AgentDefinition,
    task: str,
    provider: BaseProvider,
    max_turns: int = 8,
) -> SubagentResult:
    subruntime = runtime.create_subruntime(tool_allowlist=agent.tools)
    subprovider, resolved_model = _subagent_provider(runtime, agent, provider)
    prompt = _build_subagent_prompt(runtime, agent, task)
    result = run_query(
        subruntime,
        prompt=prompt,
        provider=subprovider,
        max_turns=agent.max_turns or runtime.settings.subagents.default_max_turns or max_turns,
    )
    summary = ""
    for message in reversed(result.messages):
        if message.get("role") == "assistant" and str(message.get("text", "")).strip():
            summary = str(message["text"]).strip()
            break
    tool_names = list(dict.fromkeys(record.tool_name for record in subruntime.tool_history))
    return SubagentResult(
        agent_name=agent.name,
        provider_name=result.provider_name,
        session_path=result.session_path,
        message_count=len(result.messages),
        tool_count=len(subruntime.tool_history),
        tool_names=tool_names,
        summary=summary,
        stop_reason=result.stop_reason,
        turn_count=result.turn_count,
        model_name=resolved_model,
    )


def _build_subagent_prompt(runtime: HarnessRuntime, agent: AgentDefinition, task: str) -> str:
    lines = [
        f"You are the subagent '{agent.name}'.",
        "",
        agent.content.strip(),
        "",
        "## Assigned Task",
        task.strip(),
        "",
        "## Working Style",
        "- Stay bounded and tool-first.",
        "- Gather evidence before concluding.",
        "- End with a concise handoff summary: findings, evidence, and the best next step for the parent agent.",
    ]
    if agent.tools:
        lines.extend(
            [
                "",
                "## Allowed Tools",
                ", ".join(agent.tools),
            ]
        )
    if _should_share_history(runtime, agent):
        history_lines = _recent_parent_context(runtime)
        if history_lines:
            lines.extend(["", "## Parent Context", *history_lines])
    include_parent_summary = (
        agent.include_parent_summary
        if agent.include_parent_summary is not None
        else runtime.settings.subagents.include_parent_summary
    )
    if include_parent_summary:
        summary = _parent_summary(runtime)
        if summary:
            lines.extend(["", "## Parent Summary", summary])
    return "\n".join(lines).strip()


def _should_share_history(runtime: HarnessRuntime, agent: AgentDefinition) -> bool:
    if agent.share_history is not None:
        return agent.share_history
    return runtime.settings.subagents.share_history


def _recent_parent_context(runtime: HarnessRuntime) -> list[str]:
    recent = runtime.messages[-6:]
    lines: list[str] = []
    for message in recent:
        role = str(message.get("role", "unknown"))
        text = str(message.get("text", "")).strip()
        if not text:
            continue
        lines.append(f"- {role}: {text[:220]}")
    return lines


def _parent_summary(runtime: HarnessRuntime) -> str:
    if runtime.active_command is not None:
        return (
            f"Active command: {runtime.active_command.name}. "
            f"Source: {runtime.active_command.source}. "
            f"Arguments: {runtime.active_command_arguments or '(none)'}"
        )
    if runtime.messages:
        last = runtime.messages[-1]
        return f"Last parent message ({last.get('role', 'unknown')}): {str(last.get('text', ''))[:220]}"
    return ""


def _subagent_provider(
    runtime: HarnessRuntime,
    agent: AgentDefinition,
    provider: BaseProvider,
) -> tuple[BaseProvider, str | None]:
    target_model = agent.model or runtime.settings.subagents.default_model
    try:
        cloned = provider.clone()
    except Exception:
        cloned = provider
    if target_model and hasattr(cloned, "model"):
        try:
            setattr(cloned, "model", target_model)
        except Exception:
            pass
    resolved_model = getattr(cloned, "model", None)
    return cloned, str(resolved_model) if resolved_model else None
