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
LINEAGE_MODES = {"NEW", "CONTINUE"}
ACTIVE_RUNTIME_STATES = {
    "Waiting", "Armed", "Paused", "BaseOnly", "Leveraged", "RecoveryProtected", "Halting",
}
RUNTIME_EVENTS = {"runtime_started", "runtime_stopped", "runtime_removed", "runtime_start_error"}
MATERIAL_EVENTS = {
    "ambiguous_position_detected",
    "entry_order_unresolved",
    "entry_cancel_reconciliation_timeout",
    "recovery_action_required",
    "worker_shutdown_timeout",
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


def load_json_text(text: str, source: str) -> dict[str, Any]:
    try:
        value = json.loads(text.lstrip("\ufeff"), object_pairs_hook=_pairs_no_duplicates)
    except json.JSONDecodeError as exc:
        raise ContractError(f"cannot read JSON from {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError("JSON root must be an object")
    return value


def load_json(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ContractError(f"cannot read JSON from {path}: {exc}") from exc
    return load_json_text(text, str(path))


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


def validate_directive(data: dict[str, Any], instance_max_quantity: int | None = None) -> None:
    required = {
        "schema_version", "kind", "id", "status", "created_at", "side",
        "window", "entry", "sizing", "retries", "stop", "target",
    }
    root = _keys(data, "directive", required | {"lineage", "notes"}, required)
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
    if base > maximum:
        raise ContractError("base_quantity must not exceed max_position_quantity")
    if instance_max_quantity is not None:
        if instance_max_quantity < 1:
            raise ContractError("instance maximum quantity must be positive")
        if maximum > instance_max_quantity:
            raise ContractError("max_position_quantity exceeds the strategy instance ceiling")
    if sizing["adds_allowed"] and (add < 1 or add_range is None):
        raise ContractError("enabled scaling requires add quantity and add range")
    if sizing["adds_allowed"] and base + add > maximum:
        raise ContractError("enabled scaling requires capacity for one complete add")
    if not sizing["adds_allowed"] and (add != 0 or add_range is not None):
        raise ContractError("disabled scaling requires add_quantity=0 and null add range")
    if not sizing["adds_allowed"] and maximum != base:
        raise ContractError("disabled scaling requires max_position_quantity=base_quantity")

    retries = _keys(root["retries"], "directive.retries",
                    {"max_base_reentries"}, {"max_base_reentries"})
    _integer(retries["max_base_reentries"], "max_base_reentries", 0, 10)
    stop_keys = {"base", "leveraged", "opposite_failure_object"}
    stop = _keys(root["stop"], "directive.stop", stop_keys, stop_keys)
    expected_stop = {
        "base": "reverse_entry_resolution",
        "leveraged": "current_sponsor_failure",
        "opposite_failure_object": "flatten",
    }
    if stop != expected_stop:
        raise ContractError("directive.stop does not match the v1 stop grammar")

    target = _keys(root["target"], "directive.target",
                   {"mode", "price", "direction", "reference"},
                   {"mode", "price", "direction"})
    if target["mode"] != "HARD_TP":
        raise ContractError("target.mode must be HARD_TP")
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
    if "lineage" in root and root["lineage"] is not None:
        lineage = _keys(root["lineage"], "directive.lineage",
                        {"mode", "parent_directive_id"}, {"mode"})
        mode = lineage["mode"]
        if mode not in LINEAGE_MODES:
            raise ContractError("directive.lineage.mode must be NEW or CONTINUE")
        parent = lineage.get("parent_directive_id")
        if mode == "NEW":
            if parent is not None:
                raise ContractError(
                    "directive.lineage.parent_directive_id must be null or absent for NEW")
        else:
            _identifier(parent, "directive.lineage.parent_directive_id")


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


def iter_jsonl_reverse(path: Path):
    if not path.exists():
        return
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        remainder = b""
        while position > 0:
            size = min(65536, position)
            position -= size
            handle.seek(position)
            parts = (handle.read(size) + remainder).split(b"\n")
            remainder = parts[0]
            for raw in reversed(parts[1:]):
                if not raw.strip():
                    continue
                try:
                    value = json.loads(raw)
                    if isinstance(value, dict):
                        yield value
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
        if remainder.strip():
            try:
                value = json.loads(remainder)
                if isinstance(value, dict):
                    yield value
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass


def tail_jsonl(path: Path, max_lines: int = 200) -> list[dict[str, Any]]:
    newest_first: list[dict[str, Any]] = []
    for value in iter_jsonl_reverse(path):
        newest_first.append(value)
        if len(newest_first) >= max_lines:
            break
    return list(reversed(newest_first))


def is_material_event(event: dict[str, Any]) -> bool:
    name = str(event.get("event", ""))
    return (name in MATERIAL_EVENTS
            or name.endswith(("_error", "_rejected", "_unresolved", "_timeout"))
            or "exception" in name)


def scan_current_session(path: Path, recent_count: int) -> dict[str, Any]:
    latest: dict[str, Any] = {
        "runtime": None,
        "directive": None,
        "control": None,
        "state": None,
    }
    recent: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for event in iter_jsonl_reverse(path):
        if len(recent) < recent_count:
            recent.append(event)
        if len(errors) < recent_count and is_material_event(event):
            errors.append(event)
        name = event.get("event")
        if latest["runtime"] is None and name in RUNTIME_EVENTS:
            latest["runtime"] = event
        if latest["directive"] is None and name in {
            "directive_accepted", "directive_rejected", "directive_mutation_rejected",
        }:
            latest["directive"] = event
        if latest["control"] is None and name in {
            "control_accepted", "control_rejected", "control_mutation_rejected",
        }:
            latest["control"] = event
        if latest["state"] is None and name in {
            "runtime_state", "position_reconciled", "recovery_action_required",
        }:
            latest["state"] = event
        if name == "runtime_started":
            break
    return {
        "latest": latest,
        "recent_errors": errors,
        "recent_events": list(reversed(recent)),
    }


def checkpoint_age_seconds(checkpoint: dict[str, Any] | None) -> float | None:
    if not checkpoint or not checkpoint.get("updated_utc"):
        return None
    try:
        updated = _timestamp(checkpoint["updated_utc"], "checkpoint.updated_utc")
    except ContractError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - updated).total_seconds())


def directive_summary(data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not data:
        return None
    return {
        "id": data.get("id"),
        "side": data.get("side"),
        "window": data.get("window"),
        "entry": data.get("entry"),
        "sizing": data.get("sizing"),
        "retries": data.get("retries"),
        "target": data.get("target"),
        "lineage": data.get("lineage"),
    }


def accepted_directive_from_checkpoint(checkpoint: dict[str, Any] | None) -> dict[str, Any]:
    raw = None if checkpoint is None else checkpoint.get("last_directive_json")
    if not isinstance(raw, str) or not raw.strip():
        raise ContractError("checkpoint does not contain a last accepted directive")
    data = load_json_text(raw, "checkpoint.last_directive_json")
    validate_directive(data)
    return data


def runtime_instance_ceiling(runtime_dir: Path, override: int | None) -> int | None:
    if override is not None:
        if override < 1:
            raise ContractError("--instance-max-quantity must be positive")
        return override
    path = runtime_paths(runtime_dir)["checkpoint"]
    if not path.exists():
        return None
    checkpoint = load_json(path)
    value = checkpoint.get("instance_max_quantity")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def status_snapshot(runtime_dir: Path, recent_count: int = 12,
                    include_raw: bool = False) -> dict[str, Any]:
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
            validate_directive(directive_file)
        except ContractError as exc:
            directive_error = str(exc)

    event_scan = scan_current_session(paths["events"], recent_count)
    latest = event_scan["latest"]
    runtime_event = latest["runtime"]
    age = checkpoint_age_seconds(checkpoint)
    worker_poll_ms = checkpoint.get("worker_poll_ms") if checkpoint else None
    freshness_limit = max(10.0, (worker_poll_ms / 1000.0) * 3.0) \
        if isinstance(worker_poll_ms, (int, float)) and not isinstance(worker_poll_ms, bool) \
        else 10.0
    lifecycle = None if runtime_event is None else runtime_event.get("event")
    if checkpoint_error or lifecycle == "runtime_start_error":
        health = "error"
    elif lifecycle in {"runtime_stopped", "runtime_removed"}:
        health = "stopped"
    elif age is not None and age <= freshness_limit:
        health = "running"
    elif lifecycle == "runtime_started" and checkpoint is None:
        health = "starting"
    elif lifecycle == "runtime_started" or checkpoint is not None:
        health = "stale"
    else:
        health = "unknown"

    state = checkpoint.get("runtime_state") if checkpoint else None
    last_accepted = None
    accepted_error = None
    if checkpoint and checkpoint.get("last_directive_json"):
        try:
            last_accepted = accepted_directive_from_checkpoint(checkpoint)
        except ContractError as exc:
            accepted_error = str(exc)
    last_accepted_id = checkpoint.get("last_directive_id") if checkpoint else None
    active_id = last_accepted_id if state in ACTIVE_RUNTIME_STATES else None
    last_outcome = latest["directive"]
    if last_outcome is None and last_accepted_id:
        last_outcome = {
            "event": "checkpoint_runtime_state",
            "directive_id": last_accepted_id,
            "runtime_state": state,
        }
    trading_enabled = checkpoint.get("trading_enabled") if checkpoint else None
    if not isinstance(trading_enabled, bool) and runtime_event is not None:
        trading_enabled = runtime_event.get("trading_enabled")
    mode = "LIVE" if trading_enabled is True else "SHADOW" if trading_enabled is False else None
    execution_symbol = checkpoint.get("execution_symbol") if checkpoint else None
    market_data_symbol = checkpoint.get("market_data_symbol") if checkpoint else None
    execution_policy = checkpoint.get("execution_policy") if checkpoint else None
    entry_interaction_mode = checkpoint.get("entry_interaction_mode") if checkpoint else None
    semantic_stop_mode = checkpoint.get("semantic_stop_mode") if checkpoint else None
    if runtime_event is not None:
        execution_symbol = execution_symbol or runtime_event.get("execution_symbol") \
            or runtime_event.get("symbol")
        market_data_symbol = market_data_symbol or runtime_event.get("market_data_symbol")
        execution_policy = execution_policy or runtime_event.get("execution_policy")
        entry_interaction_mode = entry_interaction_mode or runtime_event.get("entry_interaction_mode")
        semantic_stop_mode = semantic_stop_mode or runtime_event.get("semantic_stop_mode")

    if not entry_interaction_mode or not semantic_stop_mode:
        if execution_policy == "ES_RAIL_INTERACTION":
            entry_interaction_mode = entry_interaction_mode or "RAIL_CONTACT_ESCAPE"
            semantic_stop_mode = semantic_stop_mode or "ES_NO_REENTRY"
        elif execution_policy == "RAIL_CONTACT_ESCAPE":
            entry_interaction_mode = entry_interaction_mode or "RAIL_CONTACT_ESCAPE"
            semantic_stop_mode = semantic_stop_mode or "OFF"
        elif execution_policy == "CLASSIC_PROXIMITY_ES_SEMANTIC_STOP":
            entry_interaction_mode = entry_interaction_mode or "CLASSIC_PROXIMITY"
            semantic_stop_mode = semantic_stop_mode or "ES_NO_REENTRY"
        elif execution_policy == "NQ_CLASSIC":
            entry_interaction_mode = entry_interaction_mode or "CLASSIC_PROXIMITY"
            semantic_stop_mode = semantic_stop_mode or "OFF"
    position_quantity = checkpoint.get("position_quantity", 0) if checkpoint else 0
    working_count = checkpoint.get("bound_working_order_count", 0) if checkpoint else 0
    unresolved_count = checkpoint.get("unresolved_entry_count", 0) if checkpoint else 0
    recovery_required = bool(checkpoint and checkpoint.get("recovery_action_required"))
    evidence_state = checkpoint.get("evidence_state") if checkpoint else None
    evidence_sample_count = checkpoint.get("evidence_sample_count", 0) if checkpoint else 0
    evidence_warmup_seconds = checkpoint.get("evidence_warmup_seconds") if checkpoint else None
    evidence_required_samples = checkpoint.get("evidence_warmup_required_samples") \
        if checkpoint else None
    evidence_remaining = checkpoint.get("evidence_warmup_remaining_seconds") \
        if checkpoint else None
    blockers: list[dict[str, Any]] = []

    def block(code: str, message: str, **details: Any) -> None:
        blockers.append({"code": code, "message": message, **details})

    if health != "running":
        block("runtime_not_ready", f"runtime health is {health}", health=health)
    if recovery_required:
        block("recovery_action_required",
              "flatten the bound live position in Quantower before issuing directives")
    if isinstance(position_quantity, (int, float)) and position_quantity != 0:
        block("bound_position_not_flat", "bound position is not flat",
              quantity=position_quantity)
    if isinstance(working_count, int) and working_count > 0:
        block("bound_working_orders_exist", "bound working orders exist",
              count=working_count)
    if isinstance(unresolved_count, int) and unresolved_count > 0:
        block("entry_reconciliation_unresolved", "entry reconciliation is unresolved",
              count=unresolved_count)
    if active_id:
        block("prior_directive_active", "a prior directive is active",
              directive_id=active_id)
    if checkpoint_error:
        block("checkpoint_invalid", checkpoint_error)

    result: dict[str, Any] = {
        "runtime_dir": str(runtime_dir),
        "runtime": {
            "health": health,
            "checkpoint_age_seconds": None if age is None else round(age, 3),
            "state": state,
            "mode": mode,
            "execution_symbol": execution_symbol,
            "market_data_symbol": market_data_symbol,
            "instance_max_quantity": checkpoint.get("instance_max_quantity") if checkpoint else None,
            "execution_policy": execution_policy,
            "entry_interaction_mode": entry_interaction_mode,
            "semantic_stop_mode": semantic_stop_mode,
            "es_entry_escape_ticks": checkpoint.get("es_entry_escape_ticks") if checkpoint else None,
            "es_semantic_stop_breach_ticks": checkpoint.get("es_semantic_stop_breach_ticks")
            if checkpoint else None,
            "es_semantic_stop_hold_seconds": checkpoint.get("es_semantic_stop_hold_seconds")
            if checkpoint else None,
        },
        "directive": {
            "active_id": active_id,
            "last_accepted_id": last_accepted_id,
            "last_outcome": last_outcome,
            "last_accepted_contract": directive_summary(last_accepted),
            "accepted_contract_error": accepted_error,
            "latest_input_error": directive_error,
        },
        "position": {
            "id": checkpoint.get("position_id") if checkpoint else None,
            "direction": checkpoint.get("position_direction") if checkpoint else None,
            "quantity": position_quantity,
            "average_price": checkpoint.get("position_average_price", 0) if checkpoint else 0,
        },
        "evidence": {
            "state": evidence_state,
            "epoch_reason": checkpoint.get("evidence_epoch_reason") if checkpoint else None,
            "epoch_started_utc": checkpoint.get("evidence_epoch_started_utc")
            if checkpoint else None,
            "sample_count": evidence_sample_count,
            "required_samples": evidence_required_samples,
            "warmup_seconds": evidence_warmup_seconds,
            "warmup_remaining_seconds": evidence_remaining,
        },
        "blockers": blockers,
        "last_control_outcome": latest["control"],
        "recent_errors": event_scan["recent_errors"],
    }
    if include_raw:
        result["raw"] = {
            "checkpoint": checkpoint,
            "checkpoint_error": checkpoint_error,
            "directive_file": directive_file,
            "directive_error": directive_error,
            "latest": latest,
            "recent_events": event_scan["recent_events"],
        }
    return result


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
                     instance_max_quantity: int | None, wait_seconds: float,
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
    if not adds and args.add_quantity != 0:
        raise ContractError("--no-adds requires --add-quantity 0")
    if not adds:
        add_range = None
    elif args.add_range is not None:
        add_range = args.add_range
    elif args.side == "long":
        add_range = [args.order_range[0], args.target_price]
    else:
        add_range = [args.target_price, args.order_range[1]]
    if args.context_range is not None:
        context_range = args.context_range
    elif adds:
        context_range = [
            min(args.order_range[0], add_range[0]),
            max(args.order_range[1], add_range[1]),
        ]
    else:
        context_range = args.order_range
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
            "context_price_range": {"lower": context_range[0], "upper": context_range[1]},
            "add_price_range": None if not adds else {
                "lower": add_range[0], "upper": add_range[1]
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
            "leveraged": "current_sponsor_failure",
            "opposite_failure_object": "flatten",
        },
        "target": {
            "mode": "HARD_TP",
            "price": args.target_price,
            "direction": "above" if args.side == "long" else "below",
        },
    }
    if args.target_reference:
        data["target"]["reference"] = args.target_reference
    lineage_mode = getattr(args, "lineage_mode", "NEW")
    parent_id = getattr(args, "parent_directive_id", None)
    if lineage_mode == "CONTINUE":
        data["lineage"] = {
            "mode": "CONTINUE",
            "parent_directive_id": parent_id,
        }
    elif parent_id is not None:
        raise ContractError("--parent-directive-id requires --lineage-mode CONTINUE")
    if args.notes:
        data["notes"] = args.notes
    return data


def command_dispatch(args: argparse.Namespace) -> dict[str, Any]:
    data = build_directive(args)
    ceiling = runtime_instance_ceiling(args.runtime_dir, args.instance_max_quantity)
    return dispatch_payload(data, args.runtime_dir, ceiling,
                            args.wait_seconds, args.dry_run)


def command_validate(args: argparse.Namespace) -> dict[str, Any]:
    data = load_json(args.input)
    ceiling = runtime_instance_ceiling(args.runtime_dir, args.instance_max_quantity)
    validate_directive(data, ceiling)
    return {"outcome": "valid", "directive_id": data["id"]}


def command_reissue(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = status_snapshot(args.runtime_dir)
    source = getattr(args, "source", None)
    if source is not None:
        data = copy.deepcopy(load_json(source))
    else:
        checkpoint_path = runtime_paths(args.runtime_dir)["checkpoint"]
        if not checkpoint_path.exists():
            raise ContractError("runtime checkpoint does not exist")
        data = copy.deepcopy(accepted_directive_from_checkpoint(load_json(checkpoint_path)))
    ceiling = runtime_instance_ceiling(args.runtime_dir, args.instance_max_quantity)
    validate_directive(data, ceiling)
    continue_lineage = bool(getattr(args, "continue_lineage", False))
    parent_id = data["id"]
    blockers = snapshot["blockers"]
    if continue_lineage:
        blockers = [
            item for item in blockers
            if not (item["code"] == "prior_directive_active"
                    and item.get("directive_id") == parent_id)
        ]
    if not args.dry_run and blockers:
        codes = ", ".join(item["code"] for item in blockers)
        raise ContractError(f"reissue blocked by runtime state: {codes}")
    current = now_et()
    data["id"] = args.id or new_id("reissue", data["side"])
    data["created_at"] = timestamp(current)
    data["window"]["not_before"] = timestamp(current)
    data["window"]["expires_at"] = timestamp(
        current + timedelta(minutes=args.ttl_minutes))
    if continue_lineage:
        data["lineage"] = {
            "mode": "CONTINUE",
            "parent_directive_id": parent_id,
        }
    else:
        data.pop("lineage", None)
    note = args.reason.strip() if args.reason else ""
    if note:
        prior = data.get("notes", "").strip()
        data["notes"] = f"{prior} | Reissue: {note}".strip(" |")
    return dispatch_payload(data, args.runtime_dir, ceiling,
                            args.wait_seconds, args.dry_run)


def issue_control(runtime_dir: Path, action: str, directive_id: str | None,
                  command_id: str | None, reason: str | None,
                  wait_seconds: float, dry_run: bool) -> dict[str, Any]:
    current = now_et()
    data: dict[str, Any] = {
        "schema_version": 1,
        "kind": "CONTROL",
        "command_id": command_id or new_id(action.lower()),
        "issued_at": timestamp(current),
        "action": action,
    }
    if action == "CANCEL_DIRECTIVE":
        if not directive_id:
            raise ContractError("CANCEL_DIRECTIVE requires --directive-id")
        data["directive_id"] = directive_id
    if reason:
        data["reason"] = reason
    validate_control(data)
    if dry_run:
        return {"outcome": "validated", "control": data}
    paths = runtime_paths(runtime_dir)
    atomic_write(paths["control"], data)
    written_id = data["command_id"]
    event = wait_for_event(
        paths["events"],
        lambda item: item.get("command_id") == written_id
        and item.get("event") in {"control_accepted", "control_rejected", "control_mutation_rejected"},
        wait_seconds,
    )
    outcome = "pending" if event is None else (
        "accepted" if event.get("event") == "control_accepted" else "rejected")
    return {
        "outcome": outcome,
        "command_id": written_id,
        "path": str(paths["control"]),
        "runtime_event": event,
        "control": data,
    }


def command_control(args: argparse.Namespace) -> dict[str, Any]:
    return issue_control(
        args.runtime_dir, args.action, args.directive_id, args.id, args.reason,
        args.wait_seconds, args.dry_run)


def command_cancel_active(args: argparse.Namespace) -> dict[str, Any]:
    snapshot = status_snapshot(args.runtime_dir)
    directive_id = snapshot["directive"]["active_id"]
    if not directive_id:
        raise ContractError("no active directive is present in the runtime checkpoint")
    return issue_control(
        args.runtime_dir, "CANCEL_DIRECTIVE", directive_id, args.id, args.reason,
        args.wait_seconds, args.dry_run)


def parser() -> argparse.ArgumentParser:
    default_dir = Path(os.path.expandvars(r"%USERPROFILE%\Documents\ExecAssistantRuntime"))
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--runtime-dir", type=Path, default=default_dir)
    root.add_argument("--instance-max-quantity", type=int,
                      help="override the strategy ceiling; defaults to checkpoint metadata")
    sub = root.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status")
    status.add_argument("--recent-events", type=int, default=12)
    status.add_argument("--raw", action="store_true")

    validate = sub.add_parser("validate")
    validate.add_argument("--input", type=Path, required=True)

    dispatch = sub.add_parser("dispatch")
    dispatch.add_argument("--side", choices=["long", "short"], required=True)
    dispatch.add_argument("--order-range", type=float, nargs=2, required=True,
                          metavar=("LOWER", "UPPER"))
    dispatch.add_argument("--context-range", type=float, nargs=2,
                          metavar=("LOWER", "UPPER"),
                          help="advanced override; defaults to the minimal order/add envelope")
    dispatch.add_argument("--add-range", type=float, nargs=2, metavar=("LOWER", "UPPER"),
                          help="optional override; defaults to the base-to-target campaign envelope")
    dispatch.add_argument("--base-quantity", type=int, required=True)
    dispatch.add_argument("--add-quantity", type=int, required=True)
    dispatch.add_argument("--max-position", type=int, required=True)
    dispatch.add_argument("--no-adds", action="store_true")
    dispatch.add_argument("--max-base-reentries", type=int, default=3)
    dispatch.add_argument("--pre-entry-invalidation", type=float)
    dispatch.add_argument("--resolution", action="append", choices=sorted(RESOLUTIONS))
    dispatch.add_argument("--target-price", type=float, required=True)
    dispatch.add_argument("--target-reference")
    dispatch.add_argument("--lineage-mode", choices=sorted(LINEAGE_MODES), default="NEW")
    dispatch.add_argument("--parent-directive-id",
                          help="required when --lineage-mode CONTINUE")
    dispatch.add_argument("--not-before")
    dispatch.add_argument("--ttl-minutes", type=int, default=30)
    dispatch.add_argument("--id")
    dispatch.add_argument("--notes")
    dispatch.add_argument("--wait-seconds", type=float, default=3.0)
    dispatch.add_argument("--dry-run", action="store_true")

    def add_reissue_arguments(command: argparse.ArgumentParser, allow_source: bool) -> None:
        if allow_source:
            command.add_argument("--source", type=Path,
                                 help="explicit accepted directive source override")
        command.add_argument("--ttl-minutes", type=int, default=30)
        command.add_argument("--id")
        command.add_argument("--reason")
        command.add_argument("--continue-lineage", action="store_true",
                             help="emit lineage.mode CONTINUE using the source directive id")
        command.add_argument("--wait-seconds", type=float, default=3.0)
        command.add_argument("--dry-run", action="store_true")

    add_reissue_arguments(sub.add_parser("reissue"), allow_source=True)
    add_reissue_arguments(sub.add_parser("reissue-last-accepted"), allow_source=False)

    control = sub.add_parser("control")
    control.add_argument("--action", choices=["FLAT", "CANCEL_DIRECTIVE"], required=True)
    control.add_argument("--directive-id")
    control.add_argument("--id")
    control.add_argument("--reason")
    control.add_argument("--wait-seconds", type=float, default=3.0)
    control.add_argument("--dry-run", action="store_true")

    cancel = sub.add_parser("cancel-active")
    cancel.add_argument("--id")
    cancel.add_argument("--reason")
    cancel.add_argument("--wait-seconds", type=float, default=3.0)
    cancel.add_argument("--dry-run", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "status":
            result = status_snapshot(args.runtime_dir, args.recent_events, args.raw)
        elif args.command == "validate":
            result = command_validate(args)
        elif args.command == "dispatch":
            result = command_dispatch(args)
        elif args.command in {"reissue", "reissue-last-accepted"}:
            result = command_reissue(args)
        elif args.command == "cancel-active":
            result = command_cancel_active(args)
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
