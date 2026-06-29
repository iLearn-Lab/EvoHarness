from __future__ import annotations

import json
from typing import Any

from evo_harness.models import (
    EvolutionProposal,
    HarnessCapabilities,
    NegativeControlProbe,
    NegativeControlSource,
    OperatorName,
    TaskTrace,
)


NEGATIVE_CONTROL_STEP_PREFIX = "Run negative-control validation: "

_NEGATIVE_CONTROL_TARGET_PREFIXES = (
    "negative-control:",
    "negative_control:",
    "negative control:",
    "overclaim:",
    "overclaim-probe:",
    "overclaim_probe:",
    "near-miss:",
    "near_miss:",
)


class ValidationPlanner:
    """Build validation gates before any evolution is promoted."""

    def build_steps(
        self,
        proposal: EvolutionProposal,
        capabilities: HarnessCapabilities,
        trace: TaskTrace,
    ) -> list[str]:
        if proposal.operator == OperatorName.STOP:
            return ["Skip mutation and keep collecting traces."]

        steps: list[str] = []

        if capabilities.replay_validation:
            steps.append("Validate replay readiness and surface completeness.")
            steps.append(f"Replay the original task: {trace.task_id}")

        if capabilities.regression_suite:
            positive_targets = [target for target in trace.validation_targets if not is_negative_control_target(target)]
            command_targets = [target for target in positive_targets if looks_like_executable_validation(target)]
            semantic_targets = [target for target in positive_targets if target not in command_targets]
            if command_targets:
                for target in command_targets:
                    steps.append(f"Run regression validation: {target}")
            else:
                steps.append("Run regression validation: default regression checks")
            if semantic_targets:
                steps.append("Validate deliverable signals: " + ", ".join(semantic_targets))

        if proposal.operator == OperatorName.REVISE_SKILL and capabilities.skill_validate:
            steps.append("Validate the revised skill before promotion.")

        if proposal.operator == OperatorName.REVISE_COMMAND and capabilities.slash_commands:
            steps.append("Validate the revised command workflow before promotion.")

        if proposal.operator == OperatorName.GROW_ECOSYSTEM:
            steps.append("Validate that the new ecosystem assets are discoverable before promotion.")
            steps.append("Review whether the bundle actually shortens future engineering work.")

        for probe in collect_negative_control_probes(proposal, trace):
            steps.append(format_negative_control_step(probe))

        if capabilities.skill_rollback:
            steps.append("Keep a rollback snapshot until the next healthy run.")

        return steps

    def is_safe(self, proposal: EvolutionProposal, capabilities: HarnessCapabilities) -> bool:
        if not proposal.required_capabilities:
            return True
        return capabilities.supports(*proposal.required_capabilities)


def _looks_like_executable_validation(target: str) -> bool:
    return looks_like_executable_validation(target)


def looks_like_executable_validation(target: str) -> bool:
    lowered = str(target).strip().lower()
    if not lowered:
        return False
    executable_prefixes = (
        "python ",
        "python -m ",
        "pytest",
        "npm ",
        "pnpm ",
        "yarn ",
        "go ",
        "cargo ",
        "dotnet ",
        "mvn ",
        "gradle ",
        "make ",
        "bash ",
        "cmd ",
        "powershell ",
    )
    return lowered.startswith(executable_prefixes)


def is_negative_control_target(target: str) -> bool:
    lowered = str(target).strip().lower()
    return any(lowered.startswith(prefix) for prefix in _NEGATIVE_CONTROL_TARGET_PREFIXES)


def collect_negative_control_probes(
    proposal: EvolutionProposal,
    trace: TaskTrace,
) -> list[NegativeControlProbe]:
    probes: list[NegativeControlProbe] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add(raw: Any, *, source: NegativeControlSource, fallback_name: str) -> None:
        if raw is None:
            return
        items = _coerce_probe_items(raw)
        for index, item in enumerate(items):
            probe = _coerce_probe(item, source=source, fallback_name=f"{fallback_name}_{index + 1}")
            if probe is None or not probe.prompt:
                continue
            key = (probe.name, probe.prompt, probe.expected_outcome, probe.source)
            if key in seen:
                continue
            seen.add(key)
            probes.append(probe)

    add(trace.negative_control_probes, source="trace", fallback_name="trace_negative_control")
    add(trace.negative_control_targets, source="trace", fallback_name="trace_negative_control")
    for target in trace.validation_targets:
        if is_negative_control_target(target):
            add(_probe_payload_from_target(target), source="trace", fallback_name="trace_negative_control")

    artifacts = dict(trace.artifacts or {})
    add(artifacts.get("negative_control_probes"), source="trace", fallback_name="artifact_negative_control")
    add(artifacts.get("overclaim_probes"), source="trace", fallback_name="artifact_overclaim_probe")
    add(artifacts.get("negative_control_targets"), source="trace", fallback_name="artifact_negative_control")
    add(artifacts.get("overclaim_targets"), source="trace", fallback_name="artifact_overclaim_probe")

    add(proposal.negative_control_probes, source="proposal", fallback_name="proposal_negative_control")
    metadata = dict(proposal.metadata or {})
    add(metadata.get("negative_control_probes"), source="proposal", fallback_name="proposal_negative_control")
    add(metadata.get("overclaim_probes"), source="proposal", fallback_name="proposal_overclaim_probe")
    add(metadata.get("negative_control_targets"), source="proposal", fallback_name="proposal_negative_control")
    add(metadata.get("overclaim_targets"), source="proposal", fallback_name="proposal_overclaim_probe")

    return probes


def format_negative_control_step(probe: NegativeControlProbe) -> str:
    payload = json.dumps(probe.to_dict(), ensure_ascii=False, sort_keys=True)
    return f"{NEGATIVE_CONTROL_STEP_PREFIX}{payload}"


def parse_negative_control_step(step: str) -> NegativeControlProbe | None:
    if not step.startswith(NEGATIVE_CONTROL_STEP_PREFIX):
        return None
    payload = step[len(NEGATIVE_CONTROL_STEP_PREFIX) :].strip()
    if not payload:
        return None
    if payload.startswith("{"):
        try:
            raw = json.loads(payload)
        except json.JSONDecodeError:
            raw = payload
    else:
        raw = _probe_payload_from_target(payload)
    return NegativeControlProbe.from_raw(raw, default_source="manual", fallback_name="negative_control")


def _coerce_probe_items(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, NegativeControlProbe):
        return [raw]
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, dict):
        if any(key in raw for key in ("prompt", "target", "query", "text", "expected_outcome", "expected")):
            return [raw]
        return [value for value in raw.values()]
    if isinstance(raw, (list, tuple, set)):
        return list(raw)
    return [raw]


def _coerce_probe(
    raw: Any,
    *,
    source: NegativeControlSource,
    fallback_name: str,
) -> NegativeControlProbe | None:
    if isinstance(raw, str) and (is_negative_control_target(raw) or _looks_like_probe_spec(raw)):
        raw = _probe_payload_from_target(raw)
    try:
        return NegativeControlProbe.from_raw(raw, default_source=source, fallback_name=fallback_name)
    except (TypeError, ValueError):
        return None


def _probe_payload_from_target(target: str) -> dict[str, str]:
    text = str(target).strip()
    lowered = text.lower()
    for prefix in _NEGATIVE_CONTROL_TARGET_PREFIXES:
        if lowered.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            return {str(key): str(value) for key, value in payload.items()}

    parts = [part.strip() for part in text.split("|") if part.strip()]
    payload: dict[str, str] = {}
    prompt_parts: list[str] = []
    for part in parts:
        if "=" in part:
            key, value = part.split("=", 1)
            payload[key.strip().lower().replace("-", "_")] = value.strip()
        else:
            prompt_parts.append(part)
    prompt = payload.get("prompt") or payload.get("target") or " | ".join(prompt_parts) or text
    name = payload.get("name") or _probe_name_from_prompt(prompt)
    return {
        "name": name,
        "prompt": prompt,
        "expected_outcome": payload.get("expected_outcome") or payload.get("expected") or "decline",
        "source": payload.get("source") or "trace",
    }


def _probe_name_from_prompt(prompt: str) -> str:
    cleaned = "".join(character if character.isalnum() else "_" for character in prompt.strip().lower())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned[:48] or "negative_control"


def _looks_like_probe_spec(target: str) -> bool:
    lowered = str(target).strip().lower()
    return any(marker in lowered for marker in ("prompt=", "expected=", "expected_outcome=", "source=", "name="))
