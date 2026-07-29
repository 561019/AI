from __future__ import annotations

import tempfile
from pathlib import Path

from app.contracts import (
    CandidateImplementationReference,
    CandidateSkillTrialRequest,
    ExecutionRequest,
    HumanAction,
    HumanHandlingRequest,
)
from app.database import initialize_database
from app.engine import RuleEngineService


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        database_path = Path(temp_dir) / "rule_engine.db"
        initialize_database(database_path)
        engine = RuleEngineService(database_path)
        authorization = engine.execute(
            ExecutionRequest(
                trace_id="TRC-PATH3-SMOKE",
                request_id="REQ-PATH3-SMOKE",
                identity_context_ref="ctx-business-operator",
                claimed_actor_id="business_operator",
                business_type="temporary_margin_analysis",
                business_object_id="ORG-001",
                period="2026-Q2",
                data_reference="DS-MARGIN-TEST",
                temporary_analysis_spec={
                    "objective": "Calculate temporary revenue and gross-profit impact.",
                    "input_schema": {
                        "required_fields": [
                            "baseline_revenue",
                            "revenue_change_rate",
                            "baseline_margin",
                            "adjusted_margin",
                        ]
                    },
                    "output_schema": {
                        "required_fields": ["adjusted_revenue", "gross_profit_change"]
                    },
                    "assumptions": ["The requester confirmed the scenario variables."],
                },
            )
        )
        continuation = engine.handle_waiting_result(
            authorization.execution_record_id,
            HumanHandlingRequest(
                identity_context_ref="ctx-business-operator",
                action=HumanAction.APPROVE,
                comment="AI generation and controlled sandbox execution are authorized.",
            ),
        )
        creation = continuation.candidate_skill_creation_request
        if creation is None:
            raise SystemExit("Path-three smoke test did not return a candidate Skill creation request.")
        trial = engine.resume_candidate_skill_trial(
            authorization.execution_record_id,
            CandidateSkillTrialRequest(
                identity_context_ref="ctx-business-operator",
                candidate_implementation=CandidateImplementationReference(
                    candidate_request_id=creation.candidate_request_id,
                    artifact_ref="asset://candidate-skill/PATH3-SMOKE",
                    artifact_version="candidate-1",
                    source="digital-asset-engine:flow-simulator",
                    code_digest="path-three-smoke-digest",
                    entrypoint="calculate",
                    generation_id="GEN-PATH3-SMOKE",
                    candidate_only=True,
                ),
            ),
        )
        child = engine.execution_records.get_by_id(trial.execution_record_id)
        print(
            {
                "authorization_record_id": authorization.execution_record_id,
                "creation_request": creation.model_dump(),
                "sandbox_record_id": trial.execution_record_id,
                "state": trial.state.value,
                "reason_code": trial.reason_code,
                "result": child["result_json"],
                "candidate_asset": child["candidate_asset_reference_json"],
                "sandbox_run": child["sandbox_execution_reference_json"],
            }
        )
        if trial.reason_code != "SANDBOX_RESULT_REVIEW_REQUIRED":
            raise SystemExit("Path-three smoke test did not reach human review.")


if __name__ == "__main__":
    main()
