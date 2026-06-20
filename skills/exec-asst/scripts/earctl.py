#!/usr/bin/env python3
"""Validate and atomically operate ExecAssistantRuntime's JSON file interface."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
OFFSET_RE = re.compile(r"(?:Z|[+-][0-9]{2}:[0-9]{2})$")
RESOLUTIONS = {"direct_conversion", "supported_reclaim"}
TARGET_MODES = {
    "HARD_TP",
    "TARGET_DECISION",
    "TRAIL_AFTER_TARGET",
    "TARGET_DECISION_BEFORE_EXTREME",
}


class ContractError(ValueError):
    pass


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON property: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            value = json.load(handle, object_pairs_hook=_pairs_no_duplicates)
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError("JSON root must be an object")
    return value


def _keys(value: Any, path: str, allowed: set[str], required: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{path} must be an object")
    unknown = set(value) - allowed
    missing = required - set(value)
    if unknown:
        raise ContractError(f"{path} contains unknown properties: {', '.join(sorted(unknown))}")
    if missing:
        raise ContractError(f"{path} is missing: {', '.join(sorted(missing))}")
    return value


def _string(value: Any, path: str, max_length: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{path} must be a non-empty string")
    if max_length is not None and len(value) > max_length:
        raise ContractError(f"{path} exceeds {max_length} characters")
    return value


def _optional_text(value: Any, path: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{path} must be a string")
    if len(value) > max_length:
        raise ContractError(f"{path} exceeds {max_length} characters")
    return value


def _identifier(value: Any, path: str) -> str:
    text = _string(value, path, 128)
    if not ID_RE.fullmatch(text):
        raise ContractError(f"{path} has invalid format")
    return text


def _integer(value: Any, path: str, minimum: int, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{path} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise ContractError(f"{path} must be <= {maximum}")
    return value


def _price(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{path} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ContractError(f"{path} must be a positive finite number")
    return number


def _timestamp(value: Any, path: str) -> datetime:
    text = _string(value, path)
    if not OFFSET_RE.search(text):
        raise ContractError(f"{path} must include an RFC 3339 offset")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{path} is not a valid timestamp") from exc
    if parsed.tzinfo is None:
        raise ContractError(f"{path} must include an offset")
    return parsed


def _range(value: Any, path: str) -> tuple[float, float]:
    obj = _keys(value, path, {"lower", "upper"}, {"lower", "upper"})
    lower = _price(obj["lower"], f"{path}.lower")
    upper = _price(obj["upper"], f"{path}.upper")
    if lower > upper:
        raise ContractError(f"{path}.lower must not exceed upper")
    return lower, upper


def validate_directive(data: dict[str, Any], instance_max_quantity: int = 5) -> None:
    required = {
        "schema_version", "kind", "id", "status", "created_at", "side",
        "window", "entry", "sizing", "retries", "stop", "target",
    }
    root = _keys(data, "directive", required | {"notes"}, required)
    if root["schema_version"] != 1 or isinstance(root["schema_version"], bool):
        raise ContractError("directive.schema_version must equal 1")
    if root["kind"] != "TRADE_DIRECTIVE" or root["status"] != "active":
        raise ContractError("directive kind/status must be TRADE_DIRECTIVE/active")
    _identifier(root["id"], "directive.id")
    created = _timestamp(root["created_at"], "directive.created_at")
    side = root["side"]
    if side not in {"long", "short"}:
        raise ContractError("directive.side must be long or short")

    window = _keys(root["window"], "directive.window",
                   {"not_before", "expires_at"}, {"not_before", "expires_at"})
    not_before = _timestamp(window["not_before"], "directive.window.not_before")
    expires = _timestamp(window["expires_at"], "directive.window.expires_at")
    if expires <= not_before or created > expires:
        raise ContractError("directive window ordering is invalid")

    entry_keys = {
        "mode", "order_price_range", "context_price_range", "add_price_range",
        "pre_entry_invalidation", "allowed_resolutions",
    }
    entry = _keys(root["entry"], "directive.entry", entry_keys, entry_keys)
    if entry["mode"] != "contest_transition":
        raise ContractError("directive.entry.mode must equal contest_transition")
    order_lower, order_upper = _range(entry["order_price_range"], "order_price_range")
    context_lower, context_upper = _range(entry["context_price_range"], "context_price_range")
    if context_lower > order_lower or context_upper < order_upper:
        raise ContractError("context_price_range must contain order_price_range")
    add_range = None if entry["add_price_range"] is None else _range(
        entry["add_price_range"], "add_price_range")
    if add_range and (context_lower > add_range[0] or context_upper < add_range[1]):
        raise ContractError("context_price_range must contain add_price_range")

    invalidation = entry["pre_entry_invalidation"]
    if invalidation is not None:
        trigger = _keys(invalidation, "pre_entry_invalidation",
                        {"direction", "price"}, {"direction", "price"})
        expected = "below" if side == "long" else "above"
        if trigger["direction"] != expected:
            raise ContractError(f"pre-entry invalidation direction must be {expected}")
        _price(trigger["price"], "pre_entry_invalidation.price")

    resolutions = entry["allowed_resolutions"]
    if (not isinstance(resolutions, list) or not 1 <= len(resolutions) <= 2
            or any(not isinstance(item, str) for item in resolutions)
            or len(set(resolutions)) != len(resolutions)
            or not set(resolutions) <= RESOLUTIONS):
        raise ContractError("allowed_resolutions must contain one or both known values")

    sizing_keys = {"base_quantity", "add_quantity", "max_position_quantity", "adds_allowed"}
    sizing = _keys(root["sizing"], "directive.sizing", sizing_keys, sizing_keys)
    base = _integer(sizing["base_quantity"], "base_quantity", 1)
    add = _integer(sizing["add_quantity"], "add_quantity", 0)
    maximum = _integer(sizing["max_position_quantity"], "max_position_quantity", 1)
    if not isinstance(sizing["adds_allowed"], bool):
        raise ContractError("adds_allowed must be boolean")
    if base > maximum or maximum > max(1, instance_max_quantity):
        raise ContractError("position quantities exceed their allowed ceiling")
    if sizing["adds_allowed"] and (add < 1 or add_range is None):
        raise ContractError("enabled scaling requires add quantity and add range")
    if not sizing["adds_allowed"] and (add != 0 or add_range is not None):
        raise ContractError("disabled scaling requires add_quantity=0 and null add range")

    retries = _keys(root["retries"], "directive.retries",
                    {"max_base_reentries"}, {"max_base_reentries"})
    _integer(retries["max_base_reentries"], "max_base_reentries", 0, 10)
    stop_keys = {"base", "leveraged", "opposite_failure_object"}
    stop = _keys(root["stop"], "directive.stop", stop_keys, stop_keys)
    expected_stop = {
        "base": "reverse_entry_resolution",
        "leveraged": "weighted_breakeven",
        "opposite_failure_object": "flatten",
    }
    if stop != expected_stop:
        raise ContractError("directive.stop does not match the v1 stop grammar")

    target = _keys(root["target"], "directive.target",
                   {"mode", "price", "direction", "reference"},
                   {"mode", "price", "direction"})
    if not isinstance(target["mode"], str) or target["mode"] not in TARGET_MODES:
        raise ContractError("unknown target mode")
    target_price = _price(target["price"], "target.price")
    expected_direction = "above" if side == "long" else "below"
    if target["direction"] != expected_direction:
        raise ContractError(f"target direction must be {expected_direction}")
    if side == "long" and target_price <= order_lower:
        raise ContractError("long target must be above the order range lower boundary")
    if side == "short" and target_price >= order_upper:
        raise ContractError("short target must be below the order range upper boundary")
    if "reference" in target:
        _optional_text(target["reference"], "target.reference", 128)
    if "notes" in root:
        _optional_text(root["notes"], "directive.notes", 4096)


def validate_control(data: dict[str, Any]) -> None:
    required = {"schema_version", "kind", "command_id", "issued_at", "action"}
    root = _keys(data, "control", required | {"directive_id", "reason"}, required)
    if (root["schema_version"] != 1 or isinstance(root["schema_version"], bool)
            or root["kind"] != "CONTROL"):
        raise ContractError("control schema_version/kind is invalid")
    _identifier(root["command_id"], "control.command_id")
    _timestamp(root["issued_at"], "control.issued_at")
    action = root["action"]
    if not isinstance(action, str) or action not in {"FLAT", "CANCEL_DIRECTIVE"}:
        raise ContractError("control.action must be FLAT or CANCEL_DIRECTIVE")
    if action == "CANCEL_DIRECTIVE":
        _identifier(root.get("directive_id"), "control.directive_id")
    elif "directive_id" in root:
        raise ContractError("FLAT must not contain directive_id")
    if "reason" in root:
        _optional_text(root["reason"], "control.reason", 1024)


def now_et() -> datetime:
    utc = datetime.now(timezone.utc)
    year = utc.year
    march_first = datetime(year, 3, 1, tzinfo=timezone.utc)
    november_first = datetime(year, 11, 1, tzinfo=timezone.utc)
    second_sunday_march = 8 + ((6 - march_first.weekday()) % 7)
    first_sunday_november = 1 + ((6 - november_first.weekday()) % 7)
    dst_start_utc = datetime(year, 3, second_sunday_march, 7, tzinfo=timezone.utc)
    dst_end_utc = datetime(year, 11, first_sunday_november, 6, tzinfo=timezone.utc)
    offset_hours = -4 if dst_start_utc <= utc < dst_end_utc else -5
    return utc.astimezone(timezone(timedelta(hours=offset_hours)))


def timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def new_id(kind: str, side: str | None = None) -> str:
    current = now_et()
    pieces = [current.strftime("%Y-%m-%d"), kind]
    if side:
        pieces.append(side)
    pieces.extend([current.strftime("%H%M%S"), uuid4().hex[:6]])
    return "-".join(pieces)


def atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def runtime_paths(runtime_dir: Path) -> dict[str, Path]:
    return {
        "directive": runtime_dir / "directive.json",
        "control": runtime_dir / "control.json",
        "events": runtime_dir / "events.jsonl",
        "checkpoint": runtime_dir / "checkpoint.json",
    }


def tail_jsonl(path: Path, max_lines: int = 200) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        chunks: list[bytes] = []
        lines = 0
        while position > 0 and lines <= max_lines:
            size = min(65536, position)
            position -= size
            handle.seek(position)
            chunk = handle.read(size)
            chunks.append(chunk)
            lines += chunk.count(b"\n")
    output: list[dict[str, Any]] = []
    for raw in b"".join(reversed(chunks)).splitlines()[-max_lines:]:
        try:
            value = json.loads(raw)
            if isinstance(value, dict):
                output.append(value)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return output


def status_snapshot(runtime_dir: Path, recent_count: int = 12) -> dict[str, Any]:
    paths = runtime_paths(runtime_dir)
    checkpoint = None
    checkpoint_error = None
    if paths["checkpoint"].exists():
        try:
            checkpoint = load_json(paths["checkpoint"])
        except ContractError as exc:
            checkpoint_error = str(exc)
    directive_file = None
    directive_error = None
    if paths["directive"].exists():
        try:
            directive_file = load_json(paths["directive"])
            validate_directive(directive_file, instance_max_quantity=10_000)
        except ContractError as exc:
            directive_error = str(exc)
    events = tail_jsonl(paths["events"], 500)
    important = {
        "runtime": {"runtime_started", "runtime_stopped", "runtime_removed", "runtime_start_error"},
        "directive": {"directive_accepted", "directive_rejected", "directive_mutation_rejected"},
        "control": {"control_accepted", "control_rejected", "control_mutation_rejected"},
        "state": {"runtime_state", "position_reconciled", "recovery_action_required"},
    }
    latest: dict[str, Any] = {}
    for label, names in important.items():
        latest[label] = next((event for event in reversed(events)
                              if event.get("event") in names), None)
    latest_start = next((event for event in reversed(events)
                         if event.get("event") == "runtime_started"), None)
    runtime_event = latest["runtime"]
    errors = [event for event in events if str(event.get("event", "")).endswith("error")
              or "exception" in str(event.get("event", ""))][-recent_count:]
    return {
        "runtime_dir": str(runtime_dir),
        "runtime_running": runtime_event is not None
        and runtime_event.get("event") == "runtime_started",
        "latest_runtime_start": latest_start,
        "checkpoint": checkpoint,
        "checkpoint_error": checkpoint_error,
        "directive_file": directive_file,
        "directive_error": directive_error,
        "latest": latest,
        "recent_errors": errors,
        "recent_events": events[-recent_count:],
    }


def wait_for_event(path: Path, predicate: Callable[[dict[str, Any]], bool],
                   seconds: float) -> dict[str, Any] | None:
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        match = next((event for event in reversed(tail_jsonl(path, 300))
                      if predicate(event)), None)
        if match is not None:
            return match
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.2)


def dispatch_payload(data: dict[str, Any], runtime_dir: Path,
                     instance_max_quantity: int, wait_seconds: float,
                     dry_run: bool = False) -> dict[str, Any]:
    validate_directive(data, instance_max_quantity)
    if dry_run:
        return {"outcome": "validated", "directive": data}
    paths = runtime_paths(runtime_dir)
    atomic_write(paths["directive"], data)
    directive_id = data["id"]
    event = wait_for_event(
        paths["events"],
        lambda item: item.get("directive_id") == directive_id
        and item.get("event") in {
            "directive_accepted", "directive_rejected", "directive_mutation_rejected"
        },
        wait_seconds,
    )
    outcome = "pending" if event is None else (
        "accepted" if event.get("event") == "directive_accepted" else "rejected")
    return {
        "outcome": outcome,
        "directive_id": directive_id,
        "path": str(paths["directive"]),
        "runtime_event": event,
        "directive": data,
    }


def build_directive(args: argparse.Namespace) -> dict[str, Any]:
    current = now_et()
    not_before = _timestamp(args.not_before, "not_before") if args.not_before else current
    expires = not_before + timedelta(minutes=args.ttl_minutes)
    adds = not args.no_adds
    if adds and args.add_range is None:
        raise ContractError("--add-range is required unless --no-adds is used")
    if not adds and args.add_quantity != 0:
        raise ContractError("--no-adds requires --add-quantity 0")
    invalidation = None
    if args.pre_entry_invalidation is not None:
        invalidation = {
            "direction": "below" if args.side == "long" else "above",
            "price": args.pre_entry_invalidation,
        }
    resolutions = args.resolution or ["direct_conversion", "supported_reclaim"]
    data: dict[str, Any] = {
        "schema_version": 1,
        "kind": "TRADE_DIRECTIVE",
        "id": args.id or new_id("directive", args.side),
        "status": "active",
        "created_at": timestamp(current),
        "side": args.side,
        "window": {
            "not_before": timestamp(not_before),
            "expires_at": timestamp(expires),
        },
        "entry": {
            "mode": "contest_transition",
            "order_price_range": {"lower": args.order_range[0], "upper": args.order_range[1]},
            "context_price_range": {"lower": args.context_range[0], "upper": args.context_range[1]},
            "add_price_range": None if not adds else {
                "lower": args.add_range[0], "upper": args.add_range[1]
            },
            "pre_entry_invalidation": invalidation,
            "allowed_resolutions": resolutions,
        },
        "sizing": {
            "base_quantity": args.base_quantity,
            "add_quantity": args.add_quantity,
            "max_position_quantity": args.max_position,
            "adds_allowed": adds,
        },
        "retries": {"max_base_reentries": args.max_base_reentries},
        "stop": {
            "base": "reverse_entry_resolution",
            "leveraged": "weighted_breakeven",
            "opposite_failure_object": "flatten",
        },
        "target": {
            "mode": args.target_mode,
            "price": args.target_price,
            "direction": "above" if args.side == "long" else "below",
        },
    }
    if args.target_reference:
        data["target"]["reference"] = args.target_reference
    if args.notes:
        data["notes"] = args.notes
    return data


def command_dispatch(args: argparse.Namespace) -> dict[str, Any]:
    data = build_directive(args)
    return dispatch_payload(data, args.runtime_dir, args.instance_max_quantity,
                            args.wait_seconds, args.dry_run)


def command_validate(args: argparse.Namespace) -> dict[str, Any]:
    data = load_json(args.input)
    validate_directive(data, args.instance_max_quantity)
    return {"outcome": "valid", "directive_id": data["id"]}


def command_reissue(args: argparse.Namespace) -> dict[str, Any]:
    source = args.source or runtime_paths(args.runtime_dir)["directive"]
    data = copy.deepcopy(load_json(source))
    validate_directive(data, args.instance_max_quantity)
    current = now_et()
    data["id"] = args.id or new_id("reissue", data["side"])
    data["created_at"] = timestamp(current)
    data["window"]["not_before"] = timestamp(current)
    data["window"]["expires_at"] = timestamp(
        current + timedelta(minutes=args.ttl_minutes))
    note = args.reason.strip() if args.reason else ""
    if note:
        prior = data.get("notes", "").strip()
        data["notes"] = f"{prior} | Reissue: {note}".strip(" |")
    return dispatch_payload(data, args.runtime_dir, args.instance_max_quantity,
                            args.wait_seconds, args.dry_run)


def command_control(args: argparse.Namespace) -> dict[str, Any]:
    current = now_et()
    data: dict[str, Any] = {
        "schema_version": 1,
        "kind": "CONTROL",
        "command_id": args.id or new_id(args.action.lower()),
        "issued_at": timestamp(current),
        "action": args.action,
    }
    if args.action == "CANCEL_DIRECTIVE":
        if not args.directive_id:
            raise ContractError("CANCEL_DIRECTIVE requires --directive-id")
        data["directive_id"] = args.directive_id
    if args.reason:
        data["reason"] = args.reason
    validate_control(data)
    if args.dry_run:
        return {"outcome": "validated", "control": data}
    paths = runtime_paths(args.runtime_dir)
    atomic_write(paths["control"], data)
    command_id = data["command_id"]
    event = wait_for_event(
        paths["events"],
        lambda item: item.get("command_id") == command_id
        and item.get("event") in {"control_accepted", "control_rejected", "control_mutation_rejected"},
        args.wait_seconds,
    )
    outcome = "pending" if event is None else (
        "accepted" if event.get("event") == "control_accepted" else "rejected")
    return {
        "outcome": outcome,
        "command_id": command_id,
        "path": str(paths["control"]),
        "runtime_event": event,
        "control": data,
    }


def parser() -> argparse.ArgumentParser:
    default_dir = Path(os.path.expandvars(r"%USERPROFILE%\Documents\ExecAssistantRuntime"))
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--runtime-dir", type=Path, default=default_dir)
    root.add_argument("--instance-max-quantity", type=int, default=5)
    sub = root.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status")
    status.add_argument("--recent-events", type=int, default=12)

    validate = sub.add_parser("validate")
    validate.add_argument("--input", type=Path, required=True)

    dispatch = sub.add_parser("dispatch")
    dispatch.add_argument("--side", choices=["long", "short"], required=True)
    dispatch.add_argument("--order-range", type=float, nargs=2, required=True,
                          metavar=("LOWER", "UPPER"))
    dispatch.add_argument("--context-range", type=float, nargs=2, required=True,
                          metavar=("LOWER", "UPPER"))
    dispatch.add_argument("--add-range", type=float, nargs=2, metavar=("LOWER", "UPPER"))
    dispatch.add_argument("--base-quantity", type=int, required=True)
    dispatch.add_argument("--add-quantity", type=int, required=True)
    dispatch.add_argument("--max-position", type=int, required=True)
    dispatch.add_argument("--no-adds", action="store_true")
    dispatch.add_argument("--max-base-reentries", type=int, default=3)
    dispatch.add_argument("--pre-entry-invalidation", type=float)
    dispatch.add_argument("--resolution", action="append", choices=sorted(RESOLUTIONS))
    dispatch.add_argument("--target-mode", choices=sorted(TARGET_MODES), required=True)
    dispatch.add_argument("--target-price", type=float, required=True)
    dispatch.add_argument("--target-reference")
    dispatch.add_argument("--not-before")
    dispatch.add_argument("--ttl-minutes", type=int, default=30)
    dispatch.add_argument("--id")
    dispatch.add_argument("--notes")
    dispatch.add_argument("--wait-seconds", type=float, default=3.0)
    dispatch.add_argument("--dry-run", action="store_true")

    reissue = sub.add_parser("reissue")
    reissue.add_argument("--source", type=Path)
    reissue.add_argument("--ttl-minutes", type=int, default=30)
    reissue.add_argument("--id")
    reissue.add_argument("--reason")
    reissue.add_argument("--wait-seconds", type=float, default=3.0)
    reissue.add_argument("--dry-run", action="store_true")

    control = sub.add_parser("control")
    control.add_argument("--action", choices=["FLAT", "CANCEL_DIRECTIVE"], required=True)
    control.add_argument("--directive-id")
    control.add_argument("--id")
    control.add_argument("--reason")
    control.add_argument("--wait-seconds", type=float, default=3.0)
    control.add_argument("--dry-run", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "status":
            result = status_snapshot(args.runtime_dir, args.recent_events)
        elif args.command == "validate":
            result = command_validate(args)
        elif args.command == "dispatch":
            result = command_dispatch(args)
        elif args.command == "reissue":
            result = command_reissue(args)
        else:
            result = command_control(args)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 2 if result.get("outcome") == "rejected" else 0
    except ContractError as exc:
        print(json.dumps({"outcome": "invalid", "error": str(exc)}, indent=2),
              file=sys.stderr)
        return 2
    except OSError as exc:
        print(json.dumps({"outcome": "io_error", "error": str(exc)}, indent=2),
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
