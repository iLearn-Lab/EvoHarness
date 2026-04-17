from __future__ import annotations

from evo_harness.models import AnalysisReport, EvolutionFinding, Outcome, TaskTrace


class TraceAnalyzer:
    """Turn runtime traces into evolution-relevant findings."""

    def analyze(self, trace: TaskTrace) -> AnalysisReport:
        findings: list[EvolutionFinding] = []
        risk_score = 0.1

        if trace.outcome == Outcome.FAILURE:
            findings.append(
                EvolutionFinding(
                    kind="failed_run",
                    severity="high",
                    summary="The harness failed the current task and needs diagnosis.",
                )
            )
            risk_score += 0.2
        elif trace.outcome == Outcome.PARTIAL:
            findings.append(
                EvolutionFinding(
                    kind="partial_run",
                    severity="medium",
                    summary="The harness made progress but did not converge cleanly, so the workflow may need hardening.",
                )
            )
            risk_score += 0.12

        if trace.repeated_failures >= 2:
            findings.append(
                EvolutionFinding(
                    kind="repeated_failure",
                    severity="high",
                    summary="A similar failure pattern has repeated across recent comparable sessions.",
                )
            )
            risk_score += 0.2

        if "missing_skill" in trace.error_tags or "tool_misuse" in trace.error_tags:
            findings.append(
                EvolutionFinding(
                    kind="skill_gap",
                    severity="high",
                    summary="The trace suggests the harness is missing a reusable skill or workflow.",
                )
            )
            risk_score += 0.15

        if "command_policy_violation" in trace.error_tags or "command_policy_pressure" in trace.error_tags:
            findings.append(
                EvolutionFinding(
                    kind="command_gap",
                    severity="high",
                    summary="The active command policy or workflow appears incomplete for this task.",
                )
            )
            risk_score += 0.15

        if "exploration_loop" in trace.error_tags or "ecosystem_gap" in trace.error_tags:
            findings.append(
                EvolutionFinding(
                    kind="ecosystem_gap",
                    severity="medium",
                    summary="The session spent too many turns exploring or compensating for a thin harness ecosystem.",
                )
            )
            risk_score += 0.1

        if "capability_gap" in trace.error_tags or trace.artifacts.get("capability_gap"):
            findings.append(
                EvolutionFinding(
                    kind="capability_gap",
                    severity="high",
                    summary=(
                        "The session exposed a concrete missing capability that should be turned into a reusable "
                        "workspace asset instead of being rediscovered next time."
                    ),
                )
            )
            risk_score += 0.15

        if "provider_stall" in trace.error_tags:
            findings.append(
                EvolutionFinding(
                    kind="provider_gap",
                    severity="medium",
                    summary="The live provider stalled or produced low-yield turns, suggesting provider-aware workflow hardening is needed.",
                )
            )
            risk_score += 0.1

        if "stale_memory" in trace.error_tags:
            findings.append(
                EvolutionFinding(
                    kind="memory_drift",
                    severity="medium",
                    summary="Stored memory appears stale or misleading for this task.",
                )
            )
            risk_score += 0.1

        if trace.artifacts.get("context_truncations") or "context_pressure" in trace.error_tags:
            findings.append(
                EvolutionFinding(
                    kind="context_pressure",
                    severity="medium",
                    summary="The runtime had to trim context, which may hide relevant task state.",
                )
            )
            risk_score += 0.1

        if trace.reusable_success_pattern and trace.outcome == Outcome.SUCCESS:
            findings.append(
                EvolutionFinding(
                    kind="reusable_success",
                    severity="medium",
                    summary="The trace contains a reusable pattern worth distilling into memory.",
                )
            )

        if trace.token_budget and trace.token_cost >= int(trace.token_budget * 0.85):
            findings.append(
                EvolutionFinding(
                    kind="budget_pressure",
                    severity="medium",
                    summary="The current harness path is close to the token budget boundary.",
                )
            )
            risk_score += 0.1

        if not findings:
            findings.append(
                EvolutionFinding(
                    kind="observe_only",
                    severity="low",
                    summary="No strong evolution signal was detected from this trace.",
                )
            )

        summary = " | ".join(finding.summary for finding in findings)
        return AnalysisReport(
            task_id=trace.task_id,
            findings=findings,
            risk_score=min(risk_score, 1.0),
            summary=summary,
        )
