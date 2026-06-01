from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.config.monitor_settings import (
    ALERT_CONDITION_FIELDS,
    ALERT_CONDITION_OPERATORS,
)


def condition_matches(condition: str | None, values: dict[str, Any]) -> bool:
    if not condition or not condition.strip():
        return True
    clauses = _split_condition_clauses(condition.strip())
    if not clauses:
        raise ValueError("Condition is empty")
    return all(_evaluate_clause(clause, values) for clause in clauses)


def _split_condition_clauses(condition: str) -> list[str]:
    clauses: list[str] = []
    current: list[str] = []
    for token in condition.split():
        if token.casefold() == "and":
            if current:
                clauses.append(" ".join(current))
                current = []
            continue
        current.append(token)
    if current:
        clauses.append(" ".join(current))
    return clauses


def validate_condition(condition: str | None) -> None:
    if not condition or not condition.strip():
        return
    condition_matches(condition, {})


def _evaluate_clause(clause: str, values: dict[str, Any]) -> bool:
    field, operator, raw_expected = _parse_clause(clause)
    if field not in ALERT_CONDITION_FIELDS:
        raise ValueError(f"Unsupported condition field: {field}")
    if operator not in ALERT_CONDITION_OPERATORS:
        raise ValueError(f"Unsupported condition operator: {operator}")
    actual = values.get(field)
    if field == "price":
        return _compare_numbers(_decimal_value(actual), _decimal_value(raw_expected), operator)
    return _compare_strings(_text_value(actual), _text_value(raw_expected), operator)


def _parse_clause(clause: str) -> tuple[str, str, str]:
    text = clause.strip()
    for operator in ("<=", ">=", "==", "!=", "<", ">"):
        index = text.find(operator)
        if index < 0:
            continue
        field = text[:index].strip()
        raw_expected = text[index + len(operator) :].strip()
        if not _is_identifier(field) or not _is_supported_literal(raw_expected):
            raise ValueError("Unsupported condition syntax")
        return field, operator, raw_expected
    raise ValueError("Unsupported condition syntax")


def _is_identifier(value: str) -> bool:
    if not value:
        return False
    first = value[0]
    if not (first.isalpha() or first == "_"):
        return False
    return all(char.isalnum() or char == "_" for char in value[1:])


def _is_supported_literal(value: str) -> bool:
    if not value:
        return False
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].find(value[0]) < 0
    if _is_identifier(value):
        return True
    return _decimal_value(value) is not None


def _decimal_value(value: Any) -> Decimal | None:
    if value in (None, "", [], {}):
        return None
    text = str(value).strip().strip("\"'")
    number_text = _first_decimal_text(text)
    if number_text is None:
        return None
    try:
        return Decimal(number_text)
    except InvalidOperation:
        return None


def _first_decimal_text(text: str) -> str | None:
    start: int | None = None
    saw_digit = False
    saw_dot = False
    end: int | None = None
    for index, char in enumerate(text):
        if start is None:
            if char.isdigit() or (
                char == "-"
                and index + 1 < len(text)
                and (text[index + 1].isdigit() or text[index + 1] == ".")
            ):
                start = index
                saw_digit = char.isdigit()
            continue
        if char.isdigit():
            saw_digit = True
            continue
        if char == "." and not saw_dot:
            saw_dot = True
            continue
        end = index
        break
    if start is None:
        return None
    if end is None:
        end = len(text)
    return text[start:end] if saw_digit else None


def _text_value(value: Any) -> str:
    return " ".join(str(value or "").strip().strip("\"'").lower().split())


def _compare_numbers(actual: Decimal | None, expected: Decimal | None, operator: str) -> bool:
    if actual is None or expected is None:
        return False
    if operator == "<":
        return actual < expected
    if operator == ">":
        return actual > expected
    if operator == "<=":
        return actual <= expected
    if operator == ">=":
        return actual >= expected
    if operator == "==":
        return actual == expected
    if operator == "!=":
        return actual != expected
    return False


def _compare_strings(actual: str, expected: str, operator: str) -> bool:
    if operator == "==":
        return actual == expected
    if operator == "!=":
        return actual != expected
    raise ValueError("String conditions only support == and !=")
