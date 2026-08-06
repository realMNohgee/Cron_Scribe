#!/usr/bin/env python3
"""Cron_Scribe — Natural language to cron expression converter and validator.

Translate 'every Monday at 9am' into cron syntax and back. Zero deps.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from typing import Any

# Field indices: 0=minute, 1=hour, 2=day_of_month, 3=month, 4=day_of_week
FIELD_NAMES = ["minute", "hour", "day of month", "month", "day of week"]
DAY_NAMES = {
    "sunday": 0, "sun": 0,
    "monday": 1, "mon": 1,
    "tuesday": 2, "tue": 2, "tues": 2,
    "wednesday": 3, "wed": 3,
    "thursday": 4, "thu": 4, "thur": 4, "thurs": 4,
    "friday": 5, "fri": 5,
    "saturday": 6, "sat": 6,
}
MONTH_NAMES = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
DAY_NAMES_REVERSE = {v: k.capitalize() for k, v in DAY_NAMES.items()}
MONTH_NAMES_REVERSE = {v: k.capitalize() for k, v in MONTH_NAMES.items()}


def parse_cron_expression(expr: str) -> dict:
    """Parse a 5-field cron expression into structured data."""
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Cron expression must have 5 fields, got {len(parts)}")
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "weekday": parts[4],
        "raw": expr,
    }


def validate_field(field: str, field_name: str, min_val: int, max_val: int, allow_aliases: dict | None = None) -> list[str]:
    """Validate a single cron field. Returns list of issues (empty = valid)."""
    issues = []
    if field == "*":
        return issues

    # Handle step values: */N
    if "/" in field:
        parts = field.split("/")
        if len(parts) != 2:
            issues.append(f"{field_name}: invalid step format '{field}'")
            return issues
        base, step = parts
        try:
            step_val = int(step)
            if step_val < 1:
                issues.append(f"{field_name}: step must be >= 1, got {step_val}")
        except ValueError:
            issues.append(f"{field_name}: invalid step value '{step}'")
        if base != "*":
            return validate_field(base, field_name, min_val, max_val, allow_aliases)
        return issues

    # Handle ranges: N-M
    if "-" in field:
        parts = field.split("-")
        if len(parts) != 2:
            issues.append(f"{field_name}: invalid range format '{field}'")
            return issues
        try:
            start, end = int(parts[0]), int(parts[1])
            if start < min_val:
                issues.append(f"{field_name}: range start {start} is below minimum {min_val}")
            if end > max_val:
                issues.append(f"{field_name}: range end {end} is above maximum {max_val}")
            if start > end:
                issues.append(f"{field_name}: range start {start} > end {end}")
        except ValueError:
            issues.append(f"{field_name}: invalid range values '{field}'")
        return issues

    # Handle lists: N,M,O
    if "," in field:
        for val in field.split(","):
            try:
                v = int(val)
                if v < min_val or v > max_val:
                    issues.append(f"{field_name}: value {v} out of range [{min_val},{max_val}]")
            except ValueError:
                issues.append(f"{field_name}: invalid value in list '{val}'")
        return issues

    # Single value
    try:
        v = int(field)
        if v < min_val or v > max_val:
            issues.append(f"{field_name}: value {v} out of range [{min_val},{max_val}]")
    except ValueError:
        issues.append(f"{field_name}: invalid value '{field}'")

    return issues


def validate_expression(expr: str) -> dict:
    """Validate a cron expression, return structured result."""
    result = {"valid": True, "issues": [], "fields": {}}

    try:
        parsed = parse_cron_expression(expr)
    except ValueError as e:
        result["valid"] = False
        result["issues"].append(str(e))
        return result

    result["fields"] = parsed

    issues = []
    issues.extend(validate_field(parsed["minute"], "minute", 0, 59))
    issues.extend(validate_field(parsed["hour"], "hour", 0, 23))
    issues.extend(validate_field(parsed["day"], "day of month", 1, 31))
    issues.extend(validate_field(parsed["month"], "month", 1, 12))
    issues.extend(validate_field(parsed["weekday"], "day of week", 0, 7))

    result["issues"] = issues
    result["valid"] = len(issues) == 0

    return result


def describe_field(field: str, field_name: str, mapper: dict | None = None, unit: str = "") -> str:
    """Describe a single cron field in plain English."""
    if field == "*":
        return f"every {field_name}"

    if "/" in field:
        parts = field.split("/")
        base, step = parts
        step_desc = f"every {step}"
        if mapper and step.isdigit():
            step_desc = f"every {step} {unit}"
        if base == "*":
            if step == "1":
                return f"every {field_name}"
            return f"every {step} {field_name}"
        if step == "1":
            return describe_field(base, field_name, mapper, unit)
        return f"{describe_field(base, field_name, mapper, unit)}, every {step} {unit}"

    if "-" in field:
        parts = field.split("-")
        start, end = parts[0], parts[1]
        if mapper and start.isdigit() and end.isdigit():
            s_name = mapper.get(int(start), start)
            e_name = mapper.get(int(end), end)
            return f"from {s_name} to {e_name}"
        return f"from {start} to {end}"

    if "," in field:
        values = field.split(",")
        if mapper:
            names = [mapper.get(int(v), v) for v in values if v.isdigit()]
            if names:
                return ", ".join(str(n) for n in names)
        return ", ".join(values)

    if mapper and field.isdigit():
        return str(mapper.get(int(field), field))

    return str(field)


def explain_cron(expr: str) -> str:
    """Explain a cron expression in plain English."""
    parsed = parse_cron_expression(expr)

    parts = []

    # Minute + Hour = time
    minute_desc = parsed["minute"]
    hour_desc = parsed["hour"]

    is_specific_time = (
        minute_desc not in ("*",) and
        hour_desc not in ("*",) and
        "/" not in minute_desc and
        "/" not in hour_desc and
        "-" not in minute_desc and
        "-" not in hour_desc and
        "," not in minute_desc and
        "," not in hour_desc
    )

    if is_specific_time:
        parts.append(f"At {hour_desc.zfill(2)}:{minute_desc.zfill(2)}")
    else:
        if minute_desc == "*" and hour_desc == "*":
            parts.append("Every minute")
        elif hour_desc == "*":
            parts.append(f"At minute {minute_desc} of every hour")
        elif minute_desc == "*":
            parts.append(f"At every minute of hour {hour_desc}")
        else:
            parts.append(f"At minute {minute_desc} of hour {hour_desc}")

    # Day of month
    if parsed["day"] != "*":
        day_desc = describe_field(parsed["day"], "day")
        parts.append(f"on day {day_desc} of the month")

    # Month
    if parsed["month"] != "*":
        month_desc = describe_field(parsed["month"], "month", MONTH_NAMES_REVERSE)
        parts.append(f"in {month_desc}")

    # Day of week
    if parsed["weekday"] != "*":
        weekday_desc = describe_field(parsed["weekday"], "weekday", DAY_NAMES_REVERSE)
        parts.append(f"on {weekday_desc}")

    # If only minute is specified (every N minutes)
    if parsed["hour"] == "*" and parsed["day"] == "*" and parsed["month"] == "*" and parsed["weekday"] == "*":
        if parsed["minute"].startswith("*/"):
            return f"Every {parsed['minute'][2:]} minutes"
        if parsed["minute"] != "*" and "/" not in parsed["minute"]:
            parts = [f"At minute {parsed['minute']} of every hour"]

    # If only hour is specified (every N hours)
    if parsed["minute"] != "*" and parsed["hour"].startswith("*/") and parsed["day"] == "*" and parsed["month"] == "*" and parsed["weekday"] == "*":
        step = parsed["hour"][2:]
        return f"Every {step} hours at minute {parsed['minute']}"

    return ", ".join(parts)


def natural_to_cron(text: str) -> dict:
    """Convert natural language to a cron expression."""
    text = text.lower().strip()

    result = {
        "expression": "",
        "fields": {"minute": "*", "hour": "*", "day": "*", "month": "*", "weekday": "*"},
        "explanation": "",
        "confidence": "low",
    }

    minute = "0"
    hour = "0"
    day = "*"
    month = "*"
    weekday = "*"

    # ── Time patterns ─────────────────────────────────────────────────────────

    # "every N minutes" / "every N minute"
    m = re.search(r'every\s+(\d+)\s*minutes?', text)
    if m:
        minute = f"*/{m.group(1)}"
        result["confidence"] = "high"
        result["fields"] = {"minute": minute, "hour": "*", "day": "*", "month": "*", "weekday": "*"}
        result["expression"] = f"{minute} * * * *"
        result["explanation"] = explain_cron(result["expression"])
        return result

    # "every N hours"
    m = re.search(r'every\s+(\d+)\s*hours?', text)
    if m:
        hour_val = int(m.group(1))
        if hour_val > 23:
            result["fields"] = {"minute": "0", "hour": "*", "day": "*", "month": "*", "weekday": "*"}
            result["expression"] = "0 * * * *"
            result["explanation"] = "At the top of every hour"
            return result
        hour_field = f"*/{hour_val}"
        result["confidence"] = "high"
        result["fields"] = {"minute": "0", "hour": hour_field, "day": "*", "month": "*", "weekday": "*"}
        result["expression"] = f"0 {hour_field} * * *"
        result["explanation"] = explain_cron(result["expression"])
        return result

    # ── Parse time ────────────────────────────────────────────────────────────

    # Match various time formats
    time_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?', text)
    if time_match:
        hour_val = int(time_match.group(1))
        minute_val = int(time_match.group(2)) if time_match.group(2) else 0
        ampm = time_match.group(3)
        if ampm and ampm.startswith("p"):
            if hour_val != 12:
                hour_val += 12
        elif ampm and ampm.startswith("a") and hour_val == 12:
            hour_val = 0
        hour = str(hour_val)
        minute = str(minute_val)

    # "midnight"
    if "midnight" in text:
        hour = "0"
        minute = "0"

    # "noon"
    if "noon" in text:
        hour = "12"
        minute = "0"

    # ── Day of week ───────────────────────────────────────────────────────────

    weekdays_found = []
    for name, num in DAY_NAMES.items():
        if name in text:
            weekdays_found.append(str(num))

    # "every weekday"
    if "weekday" in text and not re.search(r'every\s+weekday', text):
        pass
    if "every weekday" in text or "weekdays" in text:
        weekday = "1-5"

    if weekdays_found:
        weekday = ",".join(sorted(set(weekdays_found), key=int))

    # "weekend" / "every Saturday and Sunday"
    if "weekend" in text or ("saturday" in text and "sunday" in text):
        weekday = "0,6"

    # ── Day of month ──────────────────────────────────────────────────────────

    # "first day of month"
    if "first day of" in text and "month" in text:
        day = "1"

    # "every day" / "daily"
    if "every day" in text or "daily" in text:
        day = "*"

    # ── Combine ───────────────────────────────────────────────────────────────

    expr = f"{minute} {hour} {day} {month} {weekday}"

    result["expression"] = expr
    result["fields"] = {"minute": minute, "hour": hour, "day": day, "month": month, "weekday": weekday}

    # Validate
    validation = validate_expression(expr)
    if validation["valid"]:
        if result["confidence"] == "low":
            result["confidence"] = "medium"
    else:
        result["issues"] = validation["issues"]

    result["explanation"] = explain_cron(expr)
    return result


def get_next_runs(expr: str, count: int = 5) -> list[str]:
    """Calculate next N run times for a cron expression."""
    parsed = parse_cron_expression(expr)
    runs = []
    now = datetime.now().replace(second=0, microsecond=0)

    # Simple approach: iterate minute by minute, check match
    current = now + timedelta(minutes=1)
    max_iterations = 525600  # 1 year of minutes

    for _ in range(max_iterations):
        if len(runs) >= count:
            break

        m = current.minute
        h = current.hour
        dom = current.day
        mon = current.month
        dow = current.weekday()  # 0=Monday, 6=Sunday (Python)
        # Convert to cron dow (0=Sunday, 6=Saturday)
        cron_dow = (dow + 1) % 7

        if _field_matches(parsed["minute"], m) and \
           _field_matches(parsed["hour"], h) and \
           _field_matches(parsed["day"], dom) and \
           _field_matches(parsed["month"], mon) and \
           _field_matches(parsed["weekday"], cron_dow):
            runs.append(current.strftime("%Y-%m-%d %H:%M:%S %A"))

        current += timedelta(minutes=1)

    return runs


def _field_matches(field: str, value: int) -> bool:
    """Check if a value matches a cron field."""
    if field == "*":
        return True

    # Step: */N
    if field.startswith("*/"):
        step = int(field[2:])
        return value % step == 0

    # Step with base: N/M
    if "/" in field:
        parts = field.split("/")
        base, step = int(parts[0]), int(parts[1])
        return value >= base and (value - base) % step == 0

    # Range: N-M
    if "-" in field:
        parts = field.split("-")
        start, end = int(parts[0]), int(parts[1])
        return start <= value <= end

    # List: N,M,O
    if "," in field:
        return str(value) in field.split(",")

    # Single value
    return int(field) == value


# ── Subcommands ───────────────────────────────────────────────────────────────

def cmd_parse(args) -> None:
    """Parse and explain a cron expression."""
    try:
        validation = validate_expression(args.expression)
    except ValueError as e:
        output({"error": str(e), "valid": False}, args.format)
        return

    explanation = explain_cron(args.expression)
    result = {
        "expression": args.expression,
        "explanation": explanation,
        "valid": validation["valid"],
        "fields": validation.get("fields", {}),
    }
    if validation["issues"]:
        result["issues"] = validation["issues"]

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        if not validation["valid"]:
            print(f"⚠ Invalid expression: {args.expression}")
            for issue in validation.get("issues", []):
                print(f"  - {issue}")
        else:
            print(f"Cron: {args.expression}")
            print(f"Meaning: {explanation}")
            if "fields" in result:
                print(f"Fields: minute={result['fields'].get('minute','')} "
                      f"hour={result['fields'].get('hour','')} "
                      f"day={result['fields'].get('day','')} "
                      f"month={result['fields'].get('month','')} "
                      f"weekday={result['fields'].get('weekday','')}")


def cmd_build(args) -> None:
    """Build a cron expression from explicit fields."""
    expr = f"{args.minute} {args.hour} {args.day} {args.month} {args.weekday}"
    validation = validate_expression(expr)

    result = {
        "expression": expr,
        "valid": validation["valid"],
        "explanation": explain_cron(expr),
        "fields": {"minute": args.minute, "hour": args.hour, "day": args.day, "month": args.month, "weekday": args.weekday},
    }
    if validation["issues"]:
        result["issues"] = validation["issues"]

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"Cron: {expr}")
        print(f"Meaning: {explain_cron(expr)}")
        if validation["issues"]:
            print("⚠ Issues:")
            for issue in validation["issues"]:
                print(f"  - {issue}")


def cmd_natural(args) -> None:
    """Convert natural language to cron."""
    result = natural_to_cron(args.text)

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"Input: \"{args.text}\"")
        print(f"Cron: {result['expression']}")
        print(f"Meaning: {result['explanation']}")
        print(f"Confidence: {result['confidence']}")
        if "issues" in result:
            print("⚠ Issues:")
            for issue in result["issues"]:
                print(f"  - {issue}")


def cmd_validate(args) -> None:
    """Validate a cron expression."""
    validation = validate_expression(args.expression)

    if args.format == "json":
        print(json.dumps(validation, indent=2))
    else:
        if validation["valid"]:
            print(f"✓ Valid: {args.expression}")
            print(f"  Meaning: {explain_cron(args.expression)}")
        else:
            print(f"✗ Invalid: {args.expression}")
            for issue in validation["issues"]:
                print(f"  - {issue}")


def cmd_next(args) -> None:
    """Calculate next N run times."""
    try:
        validation = validate_expression(args.expression)
        if not validation["valid"]:
            output({"error": "Invalid cron expression", "issues": validation["issues"]}, args.format)
            return
    except ValueError as e:
        output({"error": str(e)}, args.format)
        return

    runs = get_next_runs(args.expression, args.count)

    if args.format == "json":
        print(json.dumps({"expression": args.expression, "next_runs": runs, "count": len(runs)}, indent=2))
    else:
        print(f"Cron: {args.expression}")
        print(f"Next {len(runs)} run(s):")
        for i, run in enumerate(runs, 1):
            print(f"  {i}. {run}")


def output(data: dict, fmt: str) -> None:
    """Output data in the specified format."""
    if fmt == "json":
        print(json.dumps(data, indent=2))
    else:
        for k, v in data.items():
            print(f"{k}: {v}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cron_Scribe — Natural language to cron expression converter and validator.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cron_scribe.py parse "0 9 * * 1"
  cron_scribe.py build --minute 0 --hour 9 --weekday 1
  cron_scribe.py natural "every Monday at 9am"
  cron_scribe.py validate "0 9 * * 1"
  cron_scribe.py next "0 9 * * 1" --count 5
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    # parse
    parse_parser = subparsers.add_parser("parse", help="Parse and explain a cron expression in plain English")
    parse_parser.add_argument("expression", help="Cron expression (5 fields)")
    parse_parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")

    # build
    build_parser = subparsers.add_parser("build", help="Build a cron expression from explicit fields")
    build_parser.add_argument("--minute", default="*", help="Minute field (0-59, default: *)")
    build_parser.add_argument("--hour", default="*", help="Hour field (0-23, default: *)")
    build_parser.add_argument("--day", default="*", help="Day of month field (1-31, default: *)")
    build_parser.add_argument("--month", default="*", help="Month field (1-12, default: *)")
    build_parser.add_argument("--weekday", default="*", help="Day of week field (0-7, default: *)")
    build_parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")

    # natural
    natural_parser = subparsers.add_parser("natural", help="Convert natural language to cron expression")
    natural_parser.add_argument("text", help="Natural language description (e.g., 'every Monday at 9am')")
    natural_parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")

    # validate
    validate_parser = subparsers.add_parser("validate", help="Check if a cron expression is valid")
    validate_parser.add_argument("expression", help="Cron expression to validate")
    validate_parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")

    # next
    next_parser = subparsers.add_parser("next", help="Calculate next N run times for a cron expression")
    next_parser.add_argument("expression", help="Cron expression")
    next_parser.add_argument("--count", "-n", type=int, default=5, help="Number of next runs to calculate (default: 5)")
    next_parser.add_argument("--format", choices=["text", "json"], default="text", help="Output format")

    args = parser.parse_args()

    if args.command == "parse":
        cmd_parse(args)
    elif args.command == "build":
        cmd_build(args)
    elif args.command == "natural":
        cmd_natural(args)
    elif args.command == "validate":
        cmd_validate(args)
    elif args.command == "next":
        cmd_next(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
