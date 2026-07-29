# Rule Calculation Engine Core

This project is the first real backend implementation of the rule calculation
engine. It is separate from the UI prototype and implements the deterministic,
existing-system, and authorized temporary-sandbox paths. Bad-debt provision,
order-range audit, external payroll, and temporary margin analysis are test
data or registered capabilities, not scenario branches in the engine coordinator.

## First-phase scope

- Receive a structured request from the L2 interface boundary.
- Verify identity, action permission, and security through local adapters.
- Send every authorized calculation task to a model through the L1.5 Large Model Scheduling interface for task understanding and a candidate path/capability recommendation. The model does not supply formal business values or perform arithmetic.
- Validate the model recommendation against the published capability catalogue, governed scope, capability type, and explicit request constraints before locking a path or version.
- Block when L1.5 is unavailable, recommends an unregistered capability, or conflicts with the registered capability type; the model never performs business arithmetic or authorizes execution by itself.
- Require a unique published capability and a unique published rule version; ambiguous catalogue state is blocked instead of silently selecting the first row.
- Require the locked rule version to have a governed, timezone-aware effective time and to be effective at the request's calculation reference time.
- Derive the permission action from the published capability instead of trusting a caller-supplied action.
- Resolve authorized business data through a generic data-reference provider.
- Select an approved executor and validation profile from capability registration.
- Execute versioned declarative rules for exact/range lookup, controlled decimal formulas, conditions, and aggregates without `eval` or generated code.
- Return lookup records, formula operands, condition comparisons, aggregate reconciliation, and deterministic reason codes as calculation evidence.
- Run fixed Python capabilities and validate their result contracts.
- Route an `existing_system` capability through an internal call contract and a replaceable L1.10 Device and System Interface adapter.
- Keep external invocation evidence separate from the returned business result.
- Return `waiting_human / confirm_effective` for a key financial result.
- Persist an execution record with references, versions, validation, and trace ID.
- Include the actual business data, rule payload, capability reference, and versions in the execution digest.
- Return `waiting_human / authorize_ai_generation` when no formal capability is available.
- After authorization, return a candidate Skill creation application to the Flow Execution Engine. The Flow Execution Engine organizes the Digital Asset Engine and L1.3 Evolution Mechanism, then resumes this task with a candidate implementation reference for L1.14 Agent Execution Sandbox validation.
- Keep sandbox results reference-only even after review; they cannot be written back or registered as a formal capability automatically.
- Receive a human confirmation, termination, or recalculation request for a waiting result.
- Govern rule versions through draft, testing, review, and published states.
- Resolve the current human through the local L1.8 Account Gateway adapter before trusting an actor identity.

The local adapters and SQLite database are development replacements for future
L1.8 Account Gateway, L1.1 Permission Management, L1.9 Security and Compliance,
L1.5 Large Model Scheduling, L1.7 Data, L1.10 Device and System Interface, and L1.11 Human-AI Collaboration
integrations. They are not production authority implementations.

The platform envelope carries `actor.person_id` as an auditable claim, not a
trusted identity. During integration, the adapter can bridge that claim into a
development identity reference; when an explicit `identity_context_ref` is
present, the resolved human must match the actor claim. Records retain the
resolved actor, identity verification ID, and a SHA-256 reference digest. The
bridge is only a development assumption until the formal L1.8 Account Gateway
interface is frozen.

The engine core depends on protocol-style ports for identity, permission,
security, model-assisted task analysis, structured data, deterministic execution, and existing-system calls. Local adapters are the
defaults for development; future platform integrations can replace them through
constructor injection without changing the calculation workflow.

`LocalModelAnalysisAdapter` is only a local contract simulator for model access
through L1.5. It calls no model vendor and can only use an explicit capability
code or the legacy `business_type` hint for predictable tests. Unclassified natural-language
tasks require a real model adapter. Both the model analysis and the engine's deterministic routing
decision are stored in the execution record and included in its evidence digest.

The existing-system path currently uses `ExistingSystemCallRequest` and
`ExistingSystemCallResult` as engine-owned internal structures. The local adapter is a phase-one simulator.
Under the v0.6 target architecture, the rule engine returns an external-result dependency to the
Flow Execution Engine, which dispatches the External System Integration Engine and later resumes the
original calculation with a `system_result_ref`.
The current finance-system adapter is a simulator only. Its registered call
configuration describes the operation, required context, validation, and result
treatment; it does not copy or claim ownership of the external payroll formula.

Path three now follows the Flow-mediated contract even in the local prototype:
the requester authorizes a candidate Skill creation application; the engine returns that application
instead of calling the Digital Asset Engine; a test caller then resumes the original task with a
candidate implementation reference. The local L1.14 Agent Execution Sandbox adapter is still a
contract simulator, not production-grade isolation.

Each approved candidate Skill application carries a stable `candidate_request_id`.
The Digital Asset Engine must return the same ID with its candidate implementation
reference. Before an L1.14 trial, the engine rejects a missing or mismatched ID,
so one requester, task, authorized data scope, and candidate code remain bound to
the same auditable trial.

Capability registration, rule-version persistence, execution records, and human
handling records are accessed through L1.7-style ports. `SQLitePlatformDataAdapter`
is only the development implementation. The engine defines registration fields,
matching, and version-governance rules; it does not issue SQL or own the final
storage mechanism.

## Run

```powershell
python -m unittest discover -s tests -v
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

The current suite contains 78 automated tests. One optional in-process protocol
test uses a Flow Execution Engine reference framework when it exists beside the
project; it is skipped automatically in the standalone delivery package.

Windows users can also double-click `启动测试台.cmd` and keep its terminal
window open. This avoids requiring any command-line input.

For the path-three contract smoke test, run `启动路径三联调.cmd`. It simulates
the Flow Execution Engine returning a candidate implementation after the Digital Asset Engine
creates and registers it. The rule engine never receives a model provider key.

```powershell
python -m scripts.smoke_path_three
```

Open `http://127.0.0.1:8010/docs` for the temporary API contract.

For a business-readable manual test, open `http://127.0.0.1:8010/` or
`http://127.0.0.1:8010/test-console`. The console calls the real execution API
and shows the matched capability, locked versions, calculation result,
validation checks, state, and trace record without requiring the user to write
JSON manually.

## Platform instruction entrypoint

`GET /api/v1/capabilities` advertises the three public platform actions:
`rule.evaluate`, `rule.candidate_skill_apply`, and `rule.candidate_trial`.
`rule.calculate` remains a local backward-compatibility action only and is not
advertised for platform registration.

`POST /api/v1/instructions` accepts the platform v1 envelope. The adapter
validates the protocol, target, Flow Execution Engine caller, timezone-aware
deadline, and required idempotency key before invoking the engine.

`rule.evaluate` has two stages:

1. When no business-data reference is available, the engine verifies the
   requester at the development-adapter level, obtains a model-assisted task
   assessment, and returns a bounded `precondition_query_required` result. Its
   requirements cover formal calculation basis, published calculation
   capability, and authorized business-data references. It does not read data,
   execute a rule, or create a Skill at this stage.
2. After the Flow Execution Engine has organized the required queries and
   dispatches the task again with `context.data_refs`, the engine locks the
   applicable path and executes or returns a governed waiting/blocking result.

`business_object_ref` and `period` remain optional task hints. An optional
`calculation_as_of` fixes the business calculation reference time and must
include a timezone; when omitted, the engine uses its current time.

The local idempotency implementation uses the same scope as the platform
reference contract: caller service + action + idempotency key. It additionally
stores a semantic request digest, returns the prior task/result for an exact
replay, and rejects changed content with `idempotency_conflict`. Local records
expire after 30 days; production retention belongs to L1.7 policy.

Expired `deadline_at` values return a standard `failed / timeout` reply without
starting an execution. `data_labels` and `allowed_actions` are passed to the
permission and security ports; the rule engine does not invent their meaning or
use free-form labels to choose a calculation capability.

The envelope's `actor.person_id` is an auditable claim, not trusted identity.
If `context.identity_context_ref` is supplied, the engine resolves it through
L1.8 and blocks with `ACTOR_IDENTITY_MISMATCH` when the two humans differ. In
the current development adapter, a Flow-provided actor can be bridged into a
local identity only for protocol testing; this is not a replacement for L1.8.

For the second stage of `rule.evaluate`, `context.data_refs` must contain one
calculation input: use explicit `purpose=calculation_input` when multiple
references are supplied. A single unlabelled reference remains valid for
compatibility. Ambiguous or duplicate calculation inputs are rejected instead
of using list order. All supplied references are retained in the execution
trace; only the selected calculation input is read by the current phase-one
core.

An optional `purpose=rule_parameter` reference is consistency evidence, not an
override. When supplied, it must be unique, include a version, and match the
published parameter version locked from the capability catalogue. Formal
execution always loads the locked rule payload through the catalogue adapter;
upstream data cannot replace it. `validation_reference` remains reserved for a
later registered adapter and is not silently consumed.

## Human handling

The public platform actions `rule.candidate_skill_apply` and
`rule.candidate_trial` carry the Flow-mediated continuation after a waiting
result. When the requester authorizes AI generation, the engine returns a
candidate Skill creation application for the Flow Execution Engine; it does not
create or register an asset itself. After the Digital Asset Engine returns a
candidate implementation reference through the Flow Execution Engine, the
engine uses L1.14 Agent Execution Sandbox for trial validation. Formal
deterministic results may become effective under their treatment rule. Sandbox
results cannot automatically write back or become a formal capability. The
legacy `/v1/executions/...` handling endpoints remain local debugging helpers,
not the inter-engine public contract.

## Rule version governance

Rules are not overwritten in place. A DSM-entered draft moves through `draft -> testing -> pending_review -> published`. The designated review role approves the same transition that makes a version effective; this prototype does not invent a separate publisher role. When a new version is published, the former published version becomes `retired` and remains traceable. The calculation path reads only the current `published` version.

The local rule-version endpoints validate version governance only. In the v0.6 target architecture,
creation or modification of a Rule/Skill asset is organized by the Flow Execution Engine and handled
by the Digital Asset Engine through L1.3 Evolution Mechanism; this engine supplies the rule structure,
input/output contract, and validation requirements.

A published rule version is not executable merely because its status is
`published`. It must also carry a governed, timezone-aware `effective_at`, and
that time must be no later than the request's `calculation_as_of`. Missing,
invalid, or not-yet-effective values block execution with an explicit reason.
