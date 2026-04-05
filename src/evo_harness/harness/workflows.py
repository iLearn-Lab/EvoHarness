from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from evo_harness.harness.agents import find_agent
from evo_harness.harness.provider import BaseProvider
from evo_harness.harness.runtime import HarnessRuntime
from evo_harness.harness.subagents import SubagentResult, run_subagent


@dataclass(slots=True)
class WorkflowStep:
    agent: str
    task: str
    parallel_group: str | None = None
    share_context: bool = True
    label: str | None = None
    depends_on: list[str] = field(default_factory=list)
    children: list["WorkflowStep"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorkflowDefinition:
    name: str
    description: str
    steps: list[WorkflowStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass(slots=True)
class WorkflowResult:
    workflow_name: str
    results: list[dict[str, Any]]
    summary: str
    record_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_workflow(path: str | Path) -> WorkflowDefinition:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return WorkflowDefinition(
        name=str(payload["name"]),
        description=str(payload.get("description", "")),
        steps=[_load_step(item) for item in payload.get("steps", [])],
    )


def run_workflow(
    runtime: HarnessRuntime,
    *,
    workflow: WorkflowDefinition,
    provider_factory: callable,
    max_turns: int = 8,
) -> WorkflowResult:
    results: list[dict[str, Any]] = []
    context_notes: list[str] = []
    completed_by_label: dict[str, dict[str, Any]] = {}
    i = 0
    while i < len(workflow.steps):
        step = workflow.steps[i]
        if step.parallel_group:
            group = [step]
            j = i + 1
            while j < len(workflow.steps) and workflow.steps[j].parallel_group == step.parallel_group:
                group.append(workflow.steps[j])
                j += 1
            group_results = _run_parallel_group(
                runtime,
                group,
                provider_factory,
                context_notes=context_notes,
                completed_by_label=completed_by_label,
                max_turns=max_turns,
            )
            results.extend(group_results)
            context_notes.extend(_result_context_lines(group_results))
            for step_item, result_item in zip(group, group_results):
                if step_item.label:
                    completed_by_label[step_item.label] = result_item
            i = j
            continue
        step_result = _run_one_step(
            runtime,
            step,
            provider_factory,
            context_notes=context_notes,
            completed_by_label=completed_by_label,
            max_turns=max_turns,
        ).to_dict()
        results.append(step_result)
        context_notes.extend(_result_context_lines([step_result]))
        if step.label:
            completed_by_label[step.label] = step_result
        if step.children:
            child_results = _run_child_steps(
                runtime,
                step.children,
                provider_factory,
                parent_result=step_result,
                context_notes=context_notes,
                completed_by_label=completed_by_label,
                max_turns=max_turns,
            )
            results.extend(child_results)
            context_notes.extend(_result_context_lines(child_results))
            for child_step, child_result in zip(step.children, child_results):
                if child_step.label:
                    completed_by_label[child_step.label] = child_result
        i += 1

    summary_lines = [f"{item['agent_name']}: {item.get('summary', '')}" for item in results]
    workflow_result = WorkflowResult(
        workflow_name=workflow.name,
        results=results,
        summary="\n".join(summary_lines),
    )
    workflow_result.record_path = str(write_workflow_record(runtime.workspace, workflow_result))
    return workflow_result


def _run_parallel_group(
    runtime: HarnessRuntime,
    steps: list[WorkflowStep],
    provider_factory: callable,
    *,
    context_notes: list[str],
    completed_by_label: dict[str, dict[str, Any]],
    max_turns: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=len(steps)) as executor:
        futures = [
            executor.submit(
                _run_one_step,
                runtime,
                step,
                provider_factory,
                context_notes=list(context_notes),
                completed_by_label=dict(completed_by_label),
                max_turns=max_turns,
            )
            for step in steps
        ]
        for future in as_completed(futures):
            results.append(future.result().to_dict())
    return results


def _run_one_step(
    runtime: HarnessRuntime,
    step: WorkflowStep,
    provider_factory: callable,
    *,
    context_notes: list[str],
    completed_by_label: dict[str, dict[str, Any]],
    max_turns: int,
) -> SubagentResult:
    agent = find_agent(runtime.workspace, step.agent)
    if agent is None:
        raise ValueError(f"Agent not found for workflow step: {step.agent}")
    provider = provider_factory()
    task = _compose_task(step, context_notes, completed_by_label)
    return run_subagent(
        runtime,
        agent=agent,
        task=task,
        provider=provider,
        max_turns=max_turns,
    )


def _run_child_steps(
    runtime: HarnessRuntime,
    steps: list[WorkflowStep],
    provider_factory: callable,
    *,
    parent_result: dict[str, Any],
    context_notes: list[str],
    completed_by_label: dict[str, dict[str, Any]],
    max_turns: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    inherited_context = list(context_notes) + [
        f"parent:{parent_result['agent_name']}: {parent_result.get('summary', '')}"
    ]
    for step in steps:
        result = _run_one_step(
            runtime,
            step,
            provider_factory,
            context_notes=inherited_context,
            completed_by_label=completed_by_label,
            max_turns=max_turns,
        ).to_dict()
        results.append(result)
        inherited_context.extend(_result_context_lines([result]))
    return results


def _compose_task(
    step: WorkflowStep,
    context_notes: list[str],
    completed_by_label: dict[str, dict[str, Any]],
) -> str:
    if not step.share_context or not context_notes:
        lines = [step.task.strip()]
    else:
        lines = [step.task.strip(), "", "## Previous Workflow Context"]
        lines.extend(context_notes[-8:])
    if step.depends_on:
        lines.extend(["", "## Dependency Outputs"])
        for label in step.depends_on:
            result = completed_by_label.get(label)
            if result is None:
                continue
            lines.append(f"- {label}: {result.get('summary', '')}")
    return "\n".join(lines).strip()


def _result_context_lines(results: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in results:
        lines.append(f"{item['agent_name']}: {item.get('summary', '')}")
    return lines


def write_workflow_record(workspace: str | Path, result: WorkflowResult) -> Path:
    import datetime

    root = Path(workspace).resolve() / ".evo-harness" / "workflows"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _load_step(item: dict[str, Any]) -> WorkflowStep:
    return WorkflowStep(
        agent=str(item["agent"]),
        task=str(item["task"]),
        parallel_group=item.get("parallel_group"),
        share_context=bool(item.get("share_context", True)),
        label=item.get("label"),
        depends_on=list(item.get("depends_on", [])),
        children=[_load_step(child) for child in item.get("children", [])],
    )
