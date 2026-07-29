from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


class BadDebtProvisionValidator:
    def validate(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        line_total = sum((Decimal(line["provision"]) for line in result["lines"]), Decimal("0"))
        formula_valid = all(
            (Decimal(line["amount"]) * Decimal(line["rate"])).quantize(Decimal("0.01"))
            == Decimal(line["provision"])
            for line in result["lines"]
        )
        return [
            {
                "name": "line_formula_check",
                "passed": formula_valid,
                "detail": "Each provision equals amount multiplied by the published rate.",
            },
            {
                "name": "total_reconciliation_check",
                "passed": line_total == Decimal(result["total_provision"]),
                "detail": "The reported total equals the sum of all provision lines.",
            },
            {
                "name": "input_coverage_check",
                "passed": len(result["lines"]) > 0,
                "detail": "Every authorized input row produced one result line.",
            },
        ]


class OrderRangeAuditValidator:
    def validate(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        lines = result["lines"]
        counted_total = result["passed_count"] + result["requires_handling_count"]
        decisions_valid = all(
            (line["decision"] == "passed" and not line["reason_codes"])
            or (line["decision"] == "requires_handling" and bool(line["reason_codes"]))
            for line in lines
        )
        return [
            {
                "name": "row_coverage_check",
                "passed": result["total_count"] == len(lines) and len(lines) > 0,
                "detail": "Every authorized order produced one audit result.",
            },
            {
                "name": "decision_reason_check",
                "passed": decisions_valid,
                "detail": "Each exception decision has a deterministic reason code.",
            },
            {
                "name": "count_reconciliation_check",
                "passed": counted_total == result["total_count"],
                "detail": "Passed and exception counts reconcile to the input total.",
            },
        ]


class ExternalPayrollResultValidator:
    """Validates the returned contract without reproducing the external payroll calculation."""

    def validate(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        required_fields = {"employee_count", "gross_payroll", "deductions", "net_payroll"}
        fields_present = required_fields.issubset(result)
        numeric_values_valid = False
        totals_reconcile = False
        if fields_present:
            try:
                gross = Decimal(result["gross_payroll"])
                deductions = Decimal(result["deductions"])
                net = Decimal(result["net_payroll"])
                numeric_values_valid = (
                    int(result["employee_count"]) > 0
                    and gross >= 0
                    and deductions >= 0
                    and net >= 0
                )
                totals_reconcile = net == gross - deductions
            except (ArithmeticError, TypeError, ValueError):
                numeric_values_valid = False
        return [
            {
                "name": "external_result_contract_check",
                "passed": fields_present,
                "detail": "The external response contains all fields required by the registered result contract.",
            },
            {
                "name": "external_result_value_check",
                "passed": numeric_values_valid,
                "detail": "The external response contains a positive row count and non-negative numeric totals.",
            },
            {
                "name": "external_result_reconciliation_check",
                "passed": totals_reconcile,
                "detail": "The returned net total reconciles with the returned gross and deduction totals.",
            },
        ]


class DeclarativeRuleResultValidator:
    """Independently replays declarative formula, condition, count, and sum evidence."""

    def validate(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        lines = result.get("lines", [])
        row_coverage_valid = (
            bool(lines)
            and result.get("total_count") == len(lines)
            and result.get("passed_count", 0)
            + result.get("requires_handling_count", 0)
            == len(lines)
        )
        decisions_valid = all(
            (line.get("decision") == "passed" and not line.get("reason_codes"))
            or (
                line.get("decision") == "requires_handling"
                and bool(line.get("reason_codes"))
            )
            for line in lines
        )
        formulas_valid = all(
            self._formula_evidence_valid(evidence)
            for line in lines
            for evidence in line.get("calculation_evidence", [])
        )
        conditions_valid = all(
            self._condition_evidence_valid(evidence)
            for line in lines
            for evidence in line.get("condition_evidence", [])
        )
        aggregates_valid = all(
            self._aggregate_evidence_valid(evidence)
            for evidence in result.get("aggregate_evidence", [])
        )
        return [
            {
                "name": "declarative_row_coverage_check",
                "passed": row_coverage_valid,
                "detail": "Every authorized input row produced one declarative-rule result line.",
            },
            {
                "name": "declarative_decision_reason_check",
                "passed": decisions_valid,
                "detail": "Each failed lookup or condition has a deterministic reason code.",
            },
            {
                "name": "declarative_formula_replay_check",
                "passed": formulas_valid,
                "detail": "Every executed formula was independently recalculated from recorded operands.",
            },
            {
                "name": "declarative_condition_replay_check",
                "passed": conditions_valid,
                "detail": "Every executed condition was independently compared from recorded values.",
            },
            {
                "name": "declarative_aggregate_reconciliation_check",
                "passed": aggregates_valid,
                "detail": "Every configured count or sum reconciles with its recorded source rows.",
            },
        ]

    @classmethod
    def _formula_evidence_valid(cls, evidence: dict[str, Any]) -> bool:
        if evidence.get("status") == "skipped":
            return True
        try:
            operands = [cls._decimal(value) for value in evidence["operands"]]
            if len(operands) != 2:
                return False
            left, right = operands
            operator = evidence["operator"]
            if operator == "add":
                calculated = left + right
            elif operator == "subtract":
                calculated = left - right
            elif operator == "multiply":
                calculated = left * right
            elif operator == "divide":
                if right == 0:
                    return False
                calculated = left / right
            else:
                return False
            quantum = Decimal("1").scaleb(-int(evidence["scale"]))
            calculated = calculated.quantize(quantum, rounding=ROUND_HALF_UP)
            return calculated == cls._decimal(evidence["result"])
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return False

    @classmethod
    def _condition_evidence_valid(cls, evidence: dict[str, Any]) -> bool:
        if evidence.get("status") == "skipped":
            return True
        try:
            actual = evidence["actual"]
            expected = evidence["expected"]
            operator = evidence["operator"]
            if operator == "eq":
                replayed = actual == expected
            elif operator == "ne":
                replayed = actual != expected
            elif operator == "between":
                replayed = (
                    cls._decimal(expected[0])
                    <= cls._decimal(actual)
                    <= cls._decimal(expected[1])
                )
            else:
                left = cls._decimal(actual)
                right = cls._decimal(expected)
                comparisons = {
                    "gt": left > right,
                    "gte": left >= right,
                    "lt": left < right,
                    "lte": left <= right,
                }
                replayed = comparisons[operator]
            return replayed == evidence["passed"]
        except (KeyError, IndexError, TypeError, ValueError):
            return False

    @classmethod
    def _aggregate_evidence_valid(cls, evidence: dict[str, Any]) -> bool:
        try:
            if evidence["operator"] == "count":
                return int(evidence["result"]) == int(evidence["included_row_count"])
            if evidence["operator"] != "sum":
                return False
            total = sum(
                (cls._decimal(value) for value in evidence["source_values"]),
                Decimal("0"),
            )
            quantum = Decimal("1").scaleb(-int(evidence["scale"]))
            total = total.quantize(quantum, rounding=ROUND_HALF_UP)
            return total == cls._decimal(evidence["result"])
        except (KeyError, TypeError, ValueError, ArithmeticError):
            return False

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError) as error:
            raise ValueError(f"Value is not numeric: {value}") from error


class ValidatorRegistry:
    def __init__(self) -> None:
        self._validators = {
            "bad_debt_provision_v1": BadDebtProvisionValidator(),
            "order_range_audit_v1": OrderRangeAuditValidator(),
            "external_payroll_result_v1": ExternalPayrollResultValidator(),
            "declarative_rule_v1": DeclarativeRuleResultValidator(),
        }

    def resolve(self, validation_ref: str):
        try:
            return self._validators[validation_ref]
        except KeyError as error:
            raise ValueError(f"Registered validation profile is unavailable: {validation_ref}") from error
