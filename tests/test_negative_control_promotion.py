from __future__ import annotations

from pathlib import Path

from evo_harness.core.validator import (
    NEGATIVE_CONTROL_STEP_PREFIX,
    ValidationPlanner,
    parse_negative_control_step,
)
from evo_harness.execution import (
    ValidationResult,
    _promotion_decision,
    _run_validation_steps,
)
from evo_harness.harness.settings import PromotionPolicySettings
from evo_harness.models import (
    AnalysisReport,
    EvolutionFinding,
    EvolutionPlan,
    EvolutionProposal,
    HarnessCapabilities,
    NegativeControlProbe,
    OperatorName,
    Outcome,
    TaskTrace,
    WorkspaceSnapshot,
)


def test_planner_emits_negative_control_steps_from_trace_contract() -> None:
    trace = TaskTrace(
        task_id="task-1",
        harness="test",
        outcome=Outcome.FAILURE,
        summary="A skill should be narrower after this failure.",
        validation_targets=[
            "python -c \"raise SystemExit(0)\"",
            "negative-control:name=near_miss_scope|expected=no_match|prompt=python -c \"raise SystemExit(0)\"",
        ],
        negative_control_targets=["name=manual_near_miss|expected=decline|prompt=python -c \"raise SystemExit(1)\""],
    )
    proposal = EvolutionProposal(
        operator=OperatorName.REVISE_SKILL,
        reason="test",
        confidence=0.8,
    )
    capabilities = HarnessCapabilities(
        adapter_name="test",
        replay_validation=True,
        regression_suite=True,
        skill_validate=True,
    )

    steps = ValidationPlanner().build_steps(proposal, capabilities, trace)

    assert "Run regression validation: python -c \"raise SystemExit(0)\"" in steps
    assert all("negative-control" not in step for step in steps if step.startswith("Validate deliverable signals: "))
    negative_steps = [step for step in steps if step.startswith(NEGATIVE_CONTROL_STEP_PREFIX)]
    assert len(negative_steps) == 2
    parsed = [parse_negative_control_step(step) for step in negative_steps]
    assert [probe.name for probe in parsed if probe is not None] == ["manual_near_miss", "near_miss_scope"]
    assert [probe.expected_outcome for probe in parsed if probe is not None] == ["decline", "no_match"]


def test_negative_control_overclaim_blocks_promotion_after_positive_checks(tmp_path: Path) -> None:
    plan = _minimal_plan(
        validator_steps=[
            (
                f"{NEGATIVE_CONTROL_STEP_PREFIX}"
                '{"expected_outcome": "decline", "name": "near_miss_scope", '
                '"prompt": "python -c \\"raise SystemExit(0)\\"", "source": "manual"}'
            ),
        ],
    )

    validation = _run_validation_steps(
        plan,
        tmp_path,
        run_validation=True,
        mode="promote",
        negative_controls_enabled=True,
    )
    validation = [
        ValidationResult(step="Replay the original task: task-1", success=True, output="passed", executed=True),
        ValidationResult(
            step="Run regression validation: python -c \"raise SystemExit(0)\"",
            success=True,
            output="passed",
            executed=True,
        ),
        *validation,
    ]
    decision, assessment = _promotion_decision(
        validation,
        plan=plan,
        allow_unvalidated_promotion=False,
        workspace=tmp_path,
        policy=PromotionPolicySettings(
            min_executed_validations=1,
            require_executed_regression=True,
            require_candidate_before_promotion=False,
            min_promotion_score=0.0,
        ),
    )

    assert any(item.step.startswith(NEGATIVE_CONTROL_STEP_PREFIX) and not item.success for item in validation)
    assert decision == "reject"
    assert assessment.overclaim_hits == 1
    assert "overclaim_hits:1" in assessment.reasons
    assert "negative_control_failed" in assessment.reasons


def test_unexecuted_negative_control_blocks_when_required(tmp_path: Path) -> None:
    plan = _minimal_plan(
        validator_steps=[
            f"{NEGATIVE_CONTROL_STEP_PREFIX}"
            '{"expected_outcome": "decline", "name": "semantic_near_miss", '
            '"prompt": "near miss task that should be declined", "source": "manual"}'
        ],
    )
    validation = _run_validation_steps(
        plan,
        tmp_path,
        run_validation=True,
        mode="promote",
        negative_controls_enabled=True,
    )

    decision, assessment = _promotion_decision(
        validation,
        plan=plan,
        allow_unvalidated_promotion=False,
        workspace=tmp_path,
        policy=PromotionPolicySettings(
            min_executed_validations=0,
            require_executed_negative_controls=True,
            require_candidate_before_promotion=False,
            min_promotion_score=0.0,
        ),
    )

    assert validation[0].executed is False
    assert decision == "blocked"
    assert "negative_control_not_executed" in assessment.reasons


def _minimal_plan(*, validator_steps: list[str]) -> EvolutionPlan:
    return EvolutionPlan(
        trace=TaskTrace(
            task_id="task-1",
            harness="test",
            outcome=Outcome.SUCCESS,
            summary="test",
            artifacts={"initial_user_prompt": "do the original task"},
        ),
        capabilities=HarnessCapabilities(adapter_name="test", replay_validation=True, regression_suite=True),
        workspace=WorkspaceSnapshot(root="."),
        report=AnalysisReport(
            task_id="task-1",
            findings=[EvolutionFinding(kind="skill_gap", severity="medium", summary="test")],
            risk_score=0.0,
            summary="test",
        ),
        proposal=EvolutionProposal(
            operator=OperatorName.REVISE_SKILL,
            reason="test",
            confidence=0.8,
            validator_steps=validator_steps,
            negative_control_probes=[
                NegativeControlProbe(
                    name="near_miss_scope",
                    prompt="python -c \"raise SystemExit(0)\"",
                    expected_outcome="decline",
                    source="manual",
                )
            ],
        ),
        safe_to_apply=True,
        change_request={},
    )
