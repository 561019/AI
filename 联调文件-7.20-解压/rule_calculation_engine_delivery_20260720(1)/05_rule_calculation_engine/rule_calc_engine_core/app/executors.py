from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


MONEY_QUANTUM = Decimal("0.01")


class DeclarativeRuleExecutor:
    """Executes governed lookup, formula, and condition rules without dynamic code."""

    SUPPORTED_FORMULAS = {"add", "subtract", "multiply", "divide"}
    SUPPORTED_CONDITIONS = {"eq", "ne", "gt", "gte", "lt", "lte", "between"}

    def execute(
        self, rows: list[dict[str, Any]], rule_payload: dict[str, Any]
    ) -> dict[str, Any]:
        if rule_payload.get("rule_schema_version") != "1.0":
            raise ValueError("Unsupported declarative rule schema version.")
        operations = rule_payload.get("operations")
        if not isinstance(operations, dict):
            raise ValueError("Declarative rule operations are required.")

        parameter_tables = rule_payload.get("parameter_tables", {})
        if not isinstance(parameter_tables, dict):
            raise ValueError("Declarative parameter_tables must be an object.")
        for section in ("lookups", "formulas", "conditions", "aggregates"):
            if not isinstance(operations.get(section, []), list):
                raise ValueError(f"Declarative operation section must be a list: {section}")
        if not isinstance(operations.get("line_outputs", {}), dict):
            raise ValueError("Declarative line_outputs must be an object.")
        line_results: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            lookups: dict[str, dict[str, Any] | None] = {}
            formulas: dict[str, str] = {}
            reasons: list[str] = []
            lookup_evidence: list[dict[str, Any]] = []
            calculation_evidence: list[dict[str, Any]] = []
            condition_evidence: list[dict[str, Any]] = []

            for lookup in operations.get("lookups", []):
                name = self._required_text(lookup, "name")
                table_name = self._required_text(lookup, "table")
                table = parameter_tables.get(table_name)
                if not isinstance(table, list) or not all(
                    isinstance(item, dict) for item in table
                ):
                    raise ValueError(f"Parameter table is unavailable: {table_name}")
                matched = self._match_lookup(row, lookup, table)
                lookups[name] = matched
                if matched is None:
                    reason = lookup.get("missing_reason_code") or "LOOKUP_NOT_FOUND"
                    if reason not in reasons:
                        reasons.append(reason)
                lookup_evidence.append(
                    {
                        "name": name,
                        "type": lookup.get("type"),
                        "input_field": lookup.get("input_field"),
                        "input_value": row.get(lookup.get("input_field")),
                        "matched": matched is not None,
                        "parameter_record": matched,
                    }
                )

            for formula in operations.get("formulas", []):
                name = self._required_text(formula, "name")
                operator = self._required_text(formula, "operator")
                if operator not in self.SUPPORTED_FORMULAS:
                    raise ValueError(f"Unsupported declarative formula operator: {operator}")
                try:
                    operand_values = [
                        self._resolve_reference(ref, row, lookups, formulas)
                        for ref in formula.get("operands", [])
                    ]
                except LookupError:
                    calculation_evidence.append(
                        {"name": name, "operator": operator, "status": "skipped"}
                    )
                    continue
                if len(operand_values) != 2:
                    raise ValueError(f"Formula {name} must declare exactly two operands.")
                scale = int(formula.get("scale", 2))
                result = self._calculate(operator, operand_values, scale)
                formulas[name] = result
                calculation_evidence.append(
                    {
                        "name": name,
                        "operator": operator,
                        "operands": [str(value) for value in operand_values],
                        "scale": scale,
                        "result": result,
                        "status": "executed",
                    }
                )

            for condition in operations.get("conditions", []):
                name = self._required_text(condition, "name")
                operator = self._required_text(condition, "operator")
                if operator not in self.SUPPORTED_CONDITIONS:
                    raise ValueError(f"Unsupported declarative condition operator: {operator}")
                try:
                    actual = self._resolve_reference(
                        condition.get("left", {}), row, lookups, formulas
                    )
                    expected = self._condition_expected(
                        condition, row, lookups, formulas
                    )
                except LookupError:
                    condition_evidence.append(
                        {"name": name, "operator": operator, "status": "skipped"}
                    )
                    continue
                passed = self._compare(actual, operator, expected)
                reason_code = condition.get("reason_code")
                if not passed and reason_code and reason_code not in reasons:
                    reasons.append(reason_code)
                condition_evidence.append(
                    {
                        "name": name,
                        "operator": operator,
                        "actual": self._serializable_value(actual),
                        "expected": self._serializable_value(expected),
                        "passed": passed,
                        "reason_code": reason_code,
                        "status": "executed",
                    }
                )

            line = {
                output_name: self._resolve_output_reference(
                    reference, row, lookups, formulas
                )
                for output_name, reference in operations.get("line_outputs", {}).items()
            }
            line["decision"] = "passed" if not reasons else "requires_handling"
            line["reason_codes"] = reasons
            line["lookup_evidence"] = lookup_evidence
            line["calculation_evidence"] = calculation_evidence
            line["condition_evidence"] = condition_evidence
            line["input_row_number"] = index
            line_results.append(line)

        passed_count = sum(line["decision"] == "passed" for line in line_results)
        result: dict[str, Any] = {
            "total_count": len(line_results),
            "passed_count": passed_count,
            "requires_handling_count": len(line_results) - passed_count,
            "lines": line_results,
            "aggregate_evidence": [],
        }
        for aggregate in operations.get("aggregates", []):
            name = self._required_text(aggregate, "name")
            operator = self._required_text(aggregate, "operator")
            eligible_lines = [
                line
                for line in line_results
                if not aggregate.get("include_when_decision")
                or line["decision"] == aggregate["include_when_decision"]
            ]
            if operator == "count":
                value = len(eligible_lines)
                source_values: list[str] = []
            elif operator == "sum":
                source_name = self._required_text(aggregate, "source_output")
                source_values = [str(line[source_name]) for line in eligible_lines]
                total = sum((self._decimal(value) for value in source_values), Decimal("0"))
                scale = int(aggregate.get("scale", 2))
                value = self._format_decimal(total, scale)
            else:
                raise ValueError(f"Unsupported declarative aggregate operator: {operator}")
            result[name] = value
            result["aggregate_evidence"].append(
                {
                    "name": name,
                    "operator": operator,
                    "source_values": source_values,
                    "included_row_count": len(eligible_lines),
                    "scale": aggregate.get("scale"),
                    "result": value,
                }
            )
        return result

    @classmethod
    def _match_lookup(
        cls,
        row: dict[str, Any],
        lookup: dict[str, Any],
        table: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        input_field = cls._required_text(lookup, "input_field")
        if input_field not in row:
            raise ValueError(f"Lookup input field is missing: {input_field}")
        lookup_type = lookup.get("type")
        if lookup_type == "exact":
            match_field = cls._required_text(lookup, "match_field")
            matches = [item for item in table if item.get(match_field) == row[input_field]]
        elif lookup_type == "range":
            minimum_field = cls._required_text(lookup, "minimum_field")
            maximum_field = cls._required_text(lookup, "maximum_field")
            actual = cls._decimal(row[input_field])
            maximum_inclusive = bool(lookup.get("maximum_inclusive", False))
            matches = []
            for item in table:
                minimum = cls._decimal(item[minimum_field])
                maximum_raw = item.get(maximum_field)
                minimum_matches = actual >= minimum
                maximum_matches = maximum_raw is None or (
                    actual <= cls._decimal(maximum_raw)
                    if maximum_inclusive
                    else actual < cls._decimal(maximum_raw)
                )
                if minimum_matches and maximum_matches:
                    matches.append(item)
        else:
            raise ValueError(f"Unsupported declarative lookup type: {lookup_type}")
        if len(matches) > 1:
            raise ValueError(
                f"Parameter table contains overlapping or duplicate matches for {lookup.get('name')}."
            )
        return dict(matches[0]) if matches else None

    @classmethod
    def _resolve_reference(
        cls,
        reference: dict[str, Any],
        row: dict[str, Any],
        lookups: dict[str, dict[str, Any] | None],
        formulas: dict[str, str],
    ) -> Any:
        if "field" in reference:
            field = reference["field"]
            if field not in row:
                raise ValueError(f"Referenced input field is missing: {field}")
            return row[field]
        if "formula" in reference:
            formula = reference["formula"]
            if formula not in formulas:
                raise LookupError(formula)
            return formulas[formula]
        if "lookup" in reference:
            lookup_name = reference.get("from")
            record = lookups.get(lookup_name)
            if record is None:
                raise LookupError(str(lookup_name))
            field = reference["lookup"]
            if field not in record:
                raise ValueError(f"Referenced lookup field is missing: {field}")
            return record[field]
        if "value" in reference:
            return reference["value"]
        raise ValueError("A declarative value reference is invalid.")

    @classmethod
    def _resolve_output_reference(
        cls,
        reference: dict[str, Any],
        row: dict[str, Any],
        lookups: dict[str, dict[str, Any] | None],
        formulas: dict[str, str],
    ) -> Any:
        if "lookup_record" in reference:
            record = lookups.get(reference["lookup_record"])
            return dict(record) if record is not None else None
        try:
            return cls._resolve_reference(reference, row, lookups, formulas)
        except LookupError:
            return None

    @classmethod
    def _condition_expected(
        cls,
        condition: dict[str, Any],
        row: dict[str, Any],
        lookups: dict[str, dict[str, Any] | None],
        formulas: dict[str, str],
    ) -> Any:
        if condition["operator"] == "between":
            return [
                cls._resolve_reference(condition.get("minimum", {}), row, lookups, formulas),
                cls._resolve_reference(condition.get("maximum", {}), row, lookups, formulas),
            ]
        return cls._resolve_reference(condition.get("right", {}), row, lookups, formulas)

    @classmethod
    def _calculate(cls, operator: str, operands: list[Any], scale: int) -> str:
        left, right = (cls._decimal(value) for value in operands)
        if operator == "add":
            result = left + right
        elif operator == "subtract":
            result = left - right
        elif operator == "multiply":
            result = left * right
        elif operator == "divide":
            if right == 0:
                raise ValueError("Declarative formula division by zero is not allowed.")
            result = left / right
        else:
            raise ValueError(f"Unsupported declarative formula operator: {operator}")
        return cls._format_decimal(result, scale)

    @classmethod
    def _compare(cls, actual: Any, operator: str, expected: Any) -> bool:
        if operator in {"eq", "ne"}:
            result = actual == expected
            return result if operator == "eq" else not result
        actual_decimal = cls._decimal(actual)
        if operator == "between":
            minimum, maximum = expected
            return cls._decimal(minimum) <= actual_decimal <= cls._decimal(maximum)
        expected_decimal = cls._decimal(expected)
        comparisons = {
            "gt": actual_decimal > expected_decimal,
            "gte": actual_decimal >= expected_decimal,
            "lt": actual_decimal < expected_decimal,
            "lte": actual_decimal <= expected_decimal,
        }
        return comparisons[operator]

    @staticmethod
    def _required_text(payload: dict[str, Any], field: str) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Declarative rule field is required: {field}")
        return value

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        if isinstance(value, bool):
            raise ValueError("Boolean values cannot be used in numeric rule operations.")
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError) as error:
            raise ValueError(f"Rule value is not numeric: {value}") from error

    @staticmethod
    def _format_decimal(value: Decimal, scale: int) -> str:
        if scale < 0 or scale > 12:
            raise ValueError("Declarative formula scale must be between 0 and 12.")
        quantum = Decimal("1").scaleb(-scale)
        return str(value.quantize(quantum, rounding=ROUND_HALF_UP))

    @staticmethod
    def _serializable_value(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, list):
            return [DeclarativeRuleExecutor._serializable_value(item) for item in value]
        return value


class BadDebtProvisionExecutor:
    """Fixed deterministic capability. Rule data is supplied by the published version."""

    def execute(self, receivables: list[dict[str, Any]], rule_payload: dict[str, Any]) -> dict[str, Any]:
        lines: list[dict[str, Any]] = []
        total_balance = Decimal("0")
        total_provision = Decimal("0")
        for item in receivables:
            band = self._match_band(int(item["age_months"]), rule_payload["bands"])
            amount = Decimal(item["amount"])
            rate = Decimal(band["rate"])
            provision = (amount * rate).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
            total_balance += amount
            total_provision += provision
            lines.append(
                {
                    "receivable_id": item["receivable_id"],
                    "customer_name": item["customer_name"],
                    "amount": str(amount.quantize(MONEY_QUANTUM)),
                    "age_months": item["age_months"],
                    "band": band["label"],
                    "rate": str(rate),
                    "provision": str(provision),
                    "source_row": item["source_row"],
                    "formula": f"{amount} * {rate}",
                }
            )
        return {
            "total_balance": str(total_balance.quantize(MONEY_QUANTUM)),
            "total_provision": str(total_provision.quantize(MONEY_QUANTUM)),
            "lines": lines,
        }

    @staticmethod
    def _match_band(age_months: int, bands: list[dict[str, Any]]) -> dict[str, Any]:
        for band in bands:
            maximum = band["max_months"]
            if age_months >= band["min_months"] and (maximum is None or age_months < maximum):
                return band
        raise ValueError(f"No published band matches age_months={age_months}")


class OrderRangeAuditExecutor:
    """Test capability for deterministic price and quantity range checks."""

    def execute(self, orders: list[dict[str, Any]], rule_payload: dict[str, Any]) -> dict[str, Any]:
        rules = {item["product_type"]: item for item in rule_payload["product_rules"]}
        lines: list[dict[str, Any]] = []
        passed_count = 0
        for order in orders:
            rule = rules.get(order["product_type"])
            reasons: list[str] = []
            if rule is None:
                reasons.append("RULE_NOT_FOUND")
            else:
                price = Decimal(order["unit_price"])
                if price < Decimal(rule["min_price"]) or price > Decimal(rule["max_price"]):
                    reasons.append("PRICE_OUT_OF_RANGE")
                if int(order["quantity"]) > int(rule["max_quantity"]):
                    reasons.append("QUANTITY_OVER_LIMIT")
            decision = "passed" if not reasons else "requires_handling"
            passed_count += decision == "passed"
            lines.append(
                {
                    "order_id": order["order_id"],
                    "product_type": order["product_type"],
                    "unit_price": order["unit_price"],
                    "quantity": order["quantity"],
                    "decision": decision,
                    "reason_codes": reasons,
                    "matched_rule": rule,
                    "source_row": order["source_row"],
                }
            )
        return {
            "total_count": len(lines),
            "passed_count": passed_count,
            "requires_handling_count": len(lines) - passed_count,
            "lines": lines,
        }


class ExecutorRegistry:
    """Resolves only explicitly registered and approved implementation references."""

    def __init__(self) -> None:
        self._executors = {
            "app.executors.DeclarativeRuleExecutor": DeclarativeRuleExecutor(),
            "app.executors.BadDebtProvisionExecutor": BadDebtProvisionExecutor(),
            "app.executors.OrderRangeAuditExecutor": OrderRangeAuditExecutor(),
        }

    def resolve(self, implementation_ref: str):
        try:
            return self._executors[implementation_ref]
        except KeyError as error:
            raise ValueError(f"Registered implementation is unavailable: {implementation_ref}") from error
