from __future__ import annotations

from typing import Any, Dict

from .engine import FLOW_SERVICES, SERVICE_VERSION


def build_openapi() -> Dict[str, Any]:
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "L2 Flow Execution Engine",
            "version": SERVICE_VERSION,
            "description": "L2 flow runtime organizer. It consumes L1.2 templates and manages flow instances.",
        },
        "paths": {
            "/api/v1/instructions": {
                "post": {
                    "summary": "Platform v1 instruction envelope entrypoint",
                    "description": "Accepts the platform public envelope and returns success, accepted, or failed replies.",
                    "responses": {"200": {"description": "Standard platform reply"}},
                }
            },
            "/api/v1/callbacks": {
                "post": {
                    "summary": "Platform v1 callback envelope entrypoint",
                    "description": "Receives registered downstream callbacks through the same public envelope.",
                    "responses": {"200": {"description": "Standard platform reply"}},
                }
            },
            "/api/v1/capabilities": {"get": {"summary": "Read platform action capabilities", "responses": {"200": {"description": "Capabilities"}}}},
            "/health": {"get": {"summary": "Read runtime health and backlog counters", "responses": {"200": {"description": "Health"}}}},
            "/api/instruction": {
                "post": {
                    "summary": "Unified local demo entrypoint",
                    "requestBody": {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Instruction"}}}},
                    "responses": {"200": {"description": "Service result"}},
                }
            },
            "/api/flow/start": {"post": {"summary": "Start a flow instance", "responses": {"200": {"description": "Started instance"}}}},
            "/api/flow/get": {"post": {"summary": "Get a flow instance", "responses": {"200": {"description": "Flow instance"}}}},
            "/api/flow/list": {"post": {"summary": "List flow instances", "responses": {"200": {"description": "Flow instances"}}}},
            "/api/flow/decide": {"post": {"summary": "Decide a human task", "responses": {"200": {"description": "Updated instance"}}}},
            "/api/flow/audit": {"post": {"summary": "Read instance audit log", "responses": {"200": {"description": "Audit events"}}}},
            "/api/flow/cancel": {"post": {"summary": "Cancel a non-terminal flow instance", "responses": {"200": {"description": "Cancelled instance"}}}},
            "/api/flow/health": {"get": {"summary": "Read L2 runtime health and backlog counters", "responses": {"200": {"description": "Runtime health"}}}},
            "/api/registry": {"get": {"summary": "Read service registry", "responses": {"200": {"description": "Registry"}}}},
            "/api/openapi.json": {"get": {"summary": "Read OpenAPI contract", "responses": {"200": {"description": "OpenAPI JSON"}}}},
        },
        "components": {
            "schemas": {
                "Instruction": {
                    "type": "object",
                    "required": ["service_name", "request_type", "payload", "trace_id"],
                    "properties": {
                        "caller_layer": {"type": "string", "description": "Normally L4/L2 interface-control in production."},
                        "service_name": {"type": "string", "enum": sorted(FLOW_SERVICES)},
                        "request_type": {"type": "string", "enum": ["query", "execute", "maintain"]},
                        "actor_id": {"type": "string"},
                        "payload": {"type": "object"},
                        "trace_id": {"type": "string"},
                    },
                },
                "StartPayload": {
                    "type": "object",
                    "required": ["requester_id", "request_text"],
                    "properties": {
                        "requester_id": {"type": "string"},
                        "scope_id": {"type": "string"},
                        "request_text": {"type": "string"},
                        "intent_result": {"type": "object"},
                        "idempotency_key": {"type": "string"},
                    },
                },
                "FlowDesignPayload": {
                    "type": "object",
                    "required": ["requester_id", "request_text"],
                    "properties": {
                        "requester_id": {"type": "string"},
                        "request_text": {"type": "string"},
                        "flow_kind": {"type": "string", "enum": ["auto", "fixed", "flexible"]},
                        "intent_result": {"type": "object"},
                    },
                },
                "FlowDesignConvertPayload": {
                    "type": "object",
                    "required": ["design_id", "template_id", "human_confirmation"],
                    "properties": {
                        "design_id": {"type": "string"},
                        "template_id": {"type": "string"},
                        "template_name": {"type": "string"},
                        "category": {"type": "string"},
                        "owner_position": {"type": "string"},
                        "human_confirmation": {"type": "object"},
                    },
                },
                "HumanDecisionPayload": {
                    "type": "object",
                    "required": ["instance_id", "task_id", "decision", "decided_by"],
                    "properties": {
                        "instance_id": {"type": "string"},
                        "task_id": {"type": "string"},
                        "decision": {"type": "string", "enum": ["approved", "rejected", "modified", "answered"]},
                        "reason": {"type": "string"},
                        "decided_by": {"type": "string"},
                        "decision_payload": {"type": "object"},
                    },
                },
                "TimeoutScanPayload": {
                    "type": "object",
                    "properties": {
                        "now": {"type": "string", "format": "date-time", "description": "Optional scheduler time; defaults to current UTC time."},
                    },
                },
                "CancelPayload": {
                    "type": "object",
                    "required": ["instance_id"],
                    "properties": {
                        "instance_id": {"type": "string"},
                        "reason": {"type": "string"},
                        "cancelled_by": {"type": "string"},
                    },
                },
            }
        },
        "x-service-registry": FLOW_SERVICES,
        "x-boundary": "Consumes L1.2 templates and dispatches to L2 engine services. L2 owns flow design drafts and validation; L1.2 remains the system of record for confirmed fixed-template drafts and published versions.",
    }
