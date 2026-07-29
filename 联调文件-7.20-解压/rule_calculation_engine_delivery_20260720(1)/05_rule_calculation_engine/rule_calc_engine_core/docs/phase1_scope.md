# First-Phase Scope

The first phase implements capability-driven deterministic execution for bad
debt provision and order-range audit, plus a configuration-driven policy allowance
sample that combines parameter lookup, decimal formula execution, condition judgment,
and aggregation. It also implements an engine-owned
existing-system call contract and a local finance-system simulator for the
second path. The third path returns a Flow-mediated candidate Skill creation
application and uses a local L1.14 Agent Execution Sandbox simulator after a
candidate implementation reference is returned. It does
not implement OpenL deployment, production L1.10 Device and System Interface
integration, production sandbox isolation, workflow routing, or a production
permission system.

Every request that passes the initial identity, request-permission, and security
checks is sent to a model through the L1.5 Large Model Scheduling interface. The
engine passes through the received task fields and the available capability
summaries. The model may recommend a candidate capability and path, but the
engine validates the recommendation against the published catalogue and
registered capability type. `business_type` remains only a legacy test hint and
is no longer required from the upstream task. The current adapter is a local
contract simulator rather than a real model integration. Model unavailability
or an unverifiable recommendation blocks the task before business calculation.
The model analysis and final routing decision are retained as separate execution
evidence.

The external payroll capability is a registered integration test. The engine
passes an authorized data reference and required business context to a
replaceable adapter, validates the returned contract, and records the external
system, operation, service version, invocation ID, and data evidence. The
payroll formula remains outside the rule engine.

The public request represents a request already transferred by the L2 interface
control boundary. The engine does not model a direct L4 call.

The declarative executor accepts only registered operations and structured value
references. It does not evaluate Python expressions or arbitrary strings. Its
current operation set is exact/range lookup, add/subtract/multiply/divide, numeric
conditions, count, and sum. The output retains enough evidence for an independent
validator to replay formulas, comparisons, and aggregates.

The result state is one of `automatic_pass`, `waiting_human`, or `blocked`.
For the bad debt scenario, the published result treatment rule always returns
`waiting_human` with handling type `confirm_effective`, because it is a key
financial number.

When no published formal capability matches, the engine returns
`waiting_human / authorize_ai_generation`. Approval returns a candidate Skill
creation application to the Flow Execution Engine; it does not call the Digital
Asset Engine directly. After the Flow Execution Engine returns a candidate
implementation reference, the original task is resumed and passed to the L1.14
Agent Execution Sandbox adapter. A successful run returns
`waiting_human / review_sandbox_result`. This second review is separate from
generation authorization, and the reviewed result remains temporary reference
material rather than a formal write-back result.

The existing-system adapter remains a local phase-one simulator. Path three now
uses an explicit dependency request and task-resume input, ready for Flow
Execution Engine integration.

Execution records retain data references and an input digest. They do not copy
the full source dataset into the record by default.
