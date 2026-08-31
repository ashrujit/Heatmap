#!/usr/bin/env python3
"""Transport helper for KahnRuntime controls and campaign drafts."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from kahn_campaign_assembler import CampaignAssemblyError, build_campaign, canonical_scale_mode


DEFAULT_RUNTIME_DIR = Path.home() / "Documents" / "KahnRuntime"
DEFAULT_PROFILES = {
    "DEFAULT": DEFAULT_RUNTIME_DIR,
    "ES": DEFAULT_RUNTIME_DIR / "ES",
    "NQ": DEFAULT_RUNTIME_DIR / "NQ",
}

ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
SUPPORTED_WAYPOINT_ROLES = {
    "trap_probe",
    "trapprobe",
    "press",
    "build_trial",
    "buildtrial",
    "target",
    "no_add",
    "noadd",
    "evaluate",
    "risk",
    "repair_hold",
    "repairhold",
    "path_stress",
    "pathstress",
    "mature_path",
    "maturepath",
    "invalidation",
}


class KahnctlError(Exception):
    """User-facing command error."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise KahnctlError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def atomic_write(path: Path, payload: dict[str, Any], *, sort_keys: bool = False) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, indent=2, sort_keys=sort_keys) + "\n"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        raise KahnctlError(f"failed to write {path}: {exc}") from exc


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise KahnctlError(f"{path} not found") from exc
    except json.JSONDecodeError as exc:
        raise KahnctlError(f"{path} is not valid JSON: {exc.msg}") from exc
    except OSError as exc:
        raise KahnctlError(f"failed to read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise KahnctlError(f"{path} must contain a JSON object")
    return data


def write_result(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=False))


def runtime_dir_arg(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value))).resolve()


def path_like(value: str) -> bool:
    return (
        value.startswith(".")
        or value.startswith("~")
        or "\\" in value
        or "/" in value
        or ":" in value
        or value.startswith("%")
    )


def select_runtime(args: argparse.Namespace) -> tuple[str, Path, bool]:
    runtime_dir = getattr(args, "runtime_dir", None) or getattr(
        args,
        "global_runtime_dir",
        None,
    )
    if runtime_dir:
        return "CUSTOM", runtime_dir_arg(runtime_dir), True

    profile = getattr(args, "profile", None)
    if not profile:
        return "DEFAULT", DEFAULT_RUNTIME_DIR.resolve(), False

    key = profile.upper()
    if key in DEFAULT_PROFILES:
        return key, DEFAULT_PROFILES[key].resolve(), False

    if path_like(profile):
        return "CUSTOM", runtime_dir_arg(profile), True

    known = ", ".join(DEFAULT_PROFILES)
    raise KahnctlError(f"unknown profile {profile!r}; use one of {known} or pass a path")


def profile_paths(name: str, runtime_dir: Path) -> dict[str, str]:
    return {
        "profile": name,
        "runtime_dir": str(runtime_dir),
        "campaign_path": str(runtime_dir / "campaign.json"),
        "control_path": str(runtime_dir / "control.json"),
        "evidence_path": str(runtime_dir / "evidence.jsonl"),
        "decision_log_path": str(runtime_dir / "decisions.jsonl"),
        "checkpoint_path": str(runtime_dir / "checkpoint.json"),
    }


def build_control(action: str, reason: str | None) -> dict[str, Any]:
    created = utc_now()
    token = created.strftime("%Y%m%dT%H%M%S%fZ")
    return {
        "schema_version": 1,
        "kind": "KAHN_CONTROL",
        "id": f"kahn-{action.lower()}-{token}-{uuid4().hex[:8]}",
        "action": action.upper(),
        "reason": reason or "Operator control",
        "created_at": iso_utc(created),
    }


def same_path(left: str | Path | None, right: str | Path) -> bool:
    if not left:
        return False
    try:
        resolved_left = Path(os.path.expandvars(os.path.expanduser(str(left)))).resolve()
        resolved_right = Path(os.path.expandvars(os.path.expanduser(str(right)))).resolve()
        return resolved_left == resolved_right
    except OSError:
        return str(left).lower() == str(right).lower()


def checkpoint_updated_at(checkpoint: dict[str, Any]) -> datetime | None:
    updated = checkpoint.get("updated_utc")
    if not isinstance(updated, str):
        return None
    try:
        return parse_utc(updated, "checkpoint.updated_utc")
    except KahnctlError:
        return None


def checkpoint_fresh(checkpoint: dict[str, Any], stale_seconds: int) -> bool:
    updated = checkpoint_updated_at(checkpoint)
    if updated is None:
        return False
    age = (utc_now() - updated).total_seconds()
    return stale_seconds <= 0 or age <= stale_seconds


def expected_runtime_paths(runtime_dir: Path) -> dict[str, Path]:
    return {
        "campaign_path": runtime_dir / "campaign.json",
        "control_path": runtime_dir / "control.json",
        "evidence_path": runtime_dir / "evidence.jsonl",
        "decision_log_path": runtime_dir / "decisions.jsonl",
        "checkpoint_path": runtime_dir / "checkpoint.json",
    }


def checkpoint_path_mismatches(runtime_dir: Path, checkpoint: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []
    for key, expected in expected_runtime_paths(runtime_dir).items():
        actual = checkpoint.get(key)
        if actual and not same_path(actual, expected):
            mismatches.append(key)
    return mismatches


def checkpoint_warnings(
    runtime_dir: Path,
    checkpoint: dict[str, Any],
    *,
    stale_seconds: int,
) -> list[str]:
    warnings: list[str] = []
    for key in checkpoint_path_mismatches(runtime_dir, checkpoint):
        warnings.append(f"checkpoint_{key}_mismatch")

    actual_control = checkpoint.get("control_path")
    if actual_control and same_path(actual_control, DEFAULT_RUNTIME_DIR / "control.json"):
        warnings.append("shared_root_control_path")

    updated = checkpoint_updated_at(checkpoint)
    if updated is None:
        warnings.append("checkpoint_updated_utc_missing")
    elif stale_seconds > 0 and (utc_now() - updated).total_seconds() > stale_seconds:
        warnings.append("checkpoint_stale")

    return warnings


def number_or_zero(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def position_summary(checkpoint: dict[str, Any] | None) -> dict[str, Any]:
    data = checkpoint or {}
    quantity = number_or_zero(data.get("position_quantity"))
    return {
        "flat": abs(quantity) < 0.000001,
        "id": data.get("position_id"),
        "direction": data.get("position_direction"),
        "quantity": quantity,
        "average_price": number_or_zero(data.get("position_average_price")),
    }


def active_campaign_summary(checkpoint: dict[str, Any] | None) -> dict[str, Any]:
    data = checkpoint or {}
    status = data.get("campaign_status")
    active = isinstance(status, str) and status.lower() == "active"
    return {
        "present": bool(active and data.get("campaign_id")),
        "id": data.get("campaign_id") if active else None,
        "status": status if active else None,
    }


def candidate_control_paths(runtime_dir: Path, checkpoint: dict[str, Any] | None) -> list[Path]:
    candidates = [runtime_dir / "control.json"]
    configured = (checkpoint or {}).get("control_path")
    if configured and not same_path(configured, candidates[0]):
        candidates.append(runtime_dir_arg(str(configured)))

    result: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result


def control_file_is_stale(
    runtime_dir: Path,
    checkpoint: dict[str, Any] | None,
    *,
    stale_seconds: int,
) -> bool:
    data = checkpoint or {}
    updated = checkpoint_updated_at(data) if data else None
    last_id = data.get("last_control_id")
    last_status = data.get("last_control_status")

    for path in candidate_control_paths(runtime_dir, checkpoint):
        if not path.exists():
            continue
        try:
            control = read_json(path)
        except KahnctlError:
            return True
        control_id = control.get("id")
        if control_id and control_id == last_id and last_status:
            continue
        created_text = control.get("created_at")
        if not isinstance(created_text, str):
            return True
        try:
            created = parse_utc(created_text, "control.created_at")
        except KahnctlError:
            return True
        if updated and created <= updated:
            return True
        if stale_seconds > 0 and (utc_now() - created).total_seconds() > stale_seconds:
            return True
    return False


def preflight_assessment(
    runtime_dir: Path,
    checkpoint: dict[str, Any] | None,
    *,
    checkpoint_stale_seconds: int,
    control_stale_seconds: int,
) -> dict[str, Any]:
    data = checkpoint or {}
    running = data.get("runtime_state") == "Running"
    fresh = bool(checkpoint and checkpoint_fresh(data, checkpoint_stale_seconds))
    paths_ok = bool(checkpoint) and not checkpoint_path_mismatches(runtime_dir, data)
    position = position_summary(checkpoint)
    active_campaign = active_campaign_summary(checkpoint)
    stale_control = control_file_is_stale(
        runtime_dir,
        checkpoint,
        stale_seconds=control_stale_seconds,
    )
    phase = data.get("phase")
    ready = running and fresh and paths_ok and not stale_control
    active_blocks_dispatch = active_campaign["present"] and phase != "Retired"
    return {
        "runtime_running": running,
        "checkpoint_fresh": fresh,
        "correct_paths": paths_ok,
        "symbol_account": {
            "execution_symbol": data.get("execution_symbol"),
            "market_data_symbol": data.get("market_data_symbol"),
            "account": data.get("account"),
            "account_id": data.get("account_id"),
        },
        "phase": phase,
        "position": position,
        "active_campaign": active_campaign,
        "stale_control_file": stale_control,
        "safe": {
            "dispatch": ready and position["flat"] and not active_blocks_dispatch,
            "cancel": ready and position["flat"],
        },
    }


def command_profiles(_: argparse.Namespace) -> int:
    write_result(
        {
            "profiles": [
                profile_paths(name, runtime_dir.resolve())
                for name, runtime_dir in DEFAULT_PROFILES.items()
            ],
            "note": "Use ES/NQ profile paths in Quantower when more than one KahnRuntime instance can run.",
        }
    )
    return 0


def command_paths(args: argparse.Namespace) -> int:
    profile, runtime_dir, custom = select_runtime(args)
    payload = profile_paths(profile, runtime_dir)
    payload["custom"] = custom
    payload["quantower_inputs"] = {
        "Campaign Path": payload["campaign_path"],
        "Control Path": payload["control_path"],
        "Evidence Path": payload["evidence_path"],
        "Decision Log Path": payload["decision_log_path"],
        "Checkpoint Path": payload["checkpoint_path"],
    }
    write_result(payload)
    return 0


def command_control(args: argparse.Namespace) -> int:
    profile, runtime_dir, custom = select_runtime(args)
    shared_root = runtime_dir == DEFAULT_RUNTIME_DIR.resolve()
    if shared_root and not custom and not args.force_shared_control:
        raise KahnctlError(
            "refusing to write shared root control.json; pass ES/NQ, --runtime-dir, "
            "or --force-shared-control"
        )

    payload = build_control(args.action, args.reason)
    path = runtime_dir / "control.json"
    atomic_write(path, payload, sort_keys=True)
    write_result(
        {
            "ok": True,
            "profile": profile,
            "runtime_dir": str(runtime_dir),
            "control_path": str(path),
            "control_id": payload["id"],
            "action": payload["action"],
        }
    )
    return 0


def read_checkpoint_if_present(runtime_dir: Path) -> dict[str, Any] | None:
    path = runtime_dir / "checkpoint.json"
    if not path.exists():
        return None
    return read_json(path)


def command_preflight(args: argparse.Namespace) -> int:
    _, runtime_dir, _ = select_runtime(args)
    try:
        checkpoint = read_checkpoint_if_present(runtime_dir)
    except KahnctlError:
        checkpoint = None
    write_result(
        preflight_assessment(
            runtime_dir,
            checkpoint,
            checkpoint_stale_seconds=max(0, args.stale_seconds),
            control_stale_seconds=max(0, args.control_stale_seconds),
        )
    )
    return 0


def command_status(args: argparse.Namespace) -> int:
    profile, runtime_dir, custom = select_runtime(args)
    checkpoint_path = runtime_dir / "checkpoint.json"
    if not checkpoint_path.exists():
        write_result(
            {
                "ok": False,
                "profile": profile,
                "custom": custom,
                "runtime_dir": str(runtime_dir),
                "error": "checkpoint.json not found",
            }
        )
        return 1

    data = read_json(checkpoint_path)
    warnings = checkpoint_warnings(
        runtime_dir,
        data,
        stale_seconds=max(0, args.stale_seconds),
    )
    control_path = runtime_dir / "control.json"
    paths = profile_paths(profile, runtime_dir)
    write_result(
        {
            "ok": True,
            "profile": profile,
            "custom": custom,
            "runtime_dir": str(runtime_dir),
            "checkpoint_path": str(checkpoint_path),
            "warnings": warnings,
            "runtime_state": data.get("runtime_state"),
            "campaign_id": data.get("campaign_id"),
            "campaign_status": data.get("campaign_status"),
            "phase": data.get("phase"),
            "control": {
                "configured_path": data.get("control_path"),
                "profile_path": str(control_path),
                "profile_file_exists": control_path.exists(),
                "last_id": data.get("last_control_id"),
                "last_action": data.get("last_control_action"),
                "last_status": data.get("last_control_status"),
            },
            "paths": {
                "campaign": {
                    "configured": data.get("campaign_path"),
                    "profile": paths["campaign_path"],
                },
                "evidence": {
                    "configured": data.get("evidence_path"),
                    "profile": paths["evidence_path"],
                },
                "decision_log": {
                    "configured": data.get("decision_log_path"),
                    "profile": paths["decision_log_path"],
                },
                "checkpoint": {
                    "configured": data.get("checkpoint_path"),
                    "profile": paths["checkpoint_path"],
                },
            },
            "instance": {
                "execution_symbol": data.get("execution_symbol"),
                "market_data_symbol": data.get("market_data_symbol"),
                "account": data.get("account"),
                "account_id": data.get("account_id"),
                "trading_enabled": data.get("trading_enabled"),
            },
            "campaign": {
                "probe_quantity": data.get("campaign_probe_quantity"),
                "add_quantity": data.get("campaign_add_quantity"),
                "max_position_quantity": data.get("campaign_max_position_quantity"),
                "max_retry": data.get("campaign_max_retry"),
                "retries_remaining": data.get("execution_retries_remaining"),
            },
            "position": {
                "id": data.get("position_id"),
                "direction": data.get("position_direction"),
                "quantity": data.get("position_quantity"),
                "average_price": data.get("position_average_price"),
            },
            "updated_utc": data.get("updated_utc"),
        }
    )
    return 0


def normalize_role(value: str) -> str:
    return (value or "").replace("-", "").replace("_", "").replace(" ", "").lower()


def scale_mode_arg(value: str) -> str:
    try:
        return canonical_scale_mode(value)
    except CampaignAssemblyError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def require_scale_mode(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise KahnctlError(f"{field} must be root_only or scale_allowed")
    try:
        return canonical_scale_mode(value)
    except CampaignAssemblyError as exc:
        raise KahnctlError(f"{field} must be root_only or scale_allowed") from exc


def require_obj(data: Any, field: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise KahnctlError(f"{field} must be an object")
    return data


def require_list(data: Any, field: str) -> list[Any]:
    if not isinstance(data, list):
        raise KahnctlError(f"{field} must be an array")
    return data


def require_string(data: dict[str, Any], key: str, field: str | None = None) -> str:
    label = field or key
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise KahnctlError(f"{label} must be a non-empty string")
    return value


def require_number(data: dict[str, Any], key: str, field: str | None = None) -> float:
    label = field or key
    value = data.get(key)
    if not isinstance(value, (int, float)):
        raise KahnctlError(f"{label} must be a finite number")
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        raise KahnctlError(f"{label} must be a finite number")
    return number


def require_range(data: Any, field: str) -> tuple[float, float]:
    obj = require_obj(data, field)
    lower = require_number(obj, "lower", f"{field}.lower")
    upper = require_number(obj, "upper", f"{field}.upper")
    if lower > upper:
        lower, upper = upper, lower
    return lower, upper


def positive_int(
    data: dict[str, Any],
    key: str,
    default: int,
    field: str | None = None,
) -> int:
    label = field or key
    value = data.get(key, default)
    if not isinstance(value, int) or value < 1:
        raise KahnctlError(f"{label} must be a positive integer")
    return value


def validate_campaign(campaign: dict[str, Any], *, allow_stale: bool) -> dict[str, Any]:
    if campaign.get("schema_version") != 1:
        raise KahnctlError("campaign.schema_version must be 1")
    if campaign.get("kind") != "KAHN_CAMPAIGN":
        raise KahnctlError("campaign.kind must be KAHN_CAMPAIGN")

    campaign_id = require_string(campaign, "id")
    if not ID_PATTERN.match(campaign_id):
        raise KahnctlError("campaign.id contains unsupported characters")

    status = require_string(campaign, "status").lower()
    if status not in {"active", "draft"}:
        raise KahnctlError("campaign.status must be active or draft")

    side = require_string(campaign, "side").lower()
    if side not in {"long", "short"}:
        raise KahnctlError("campaign.side must be long or short")

    parse_utc(require_string(campaign, "created_at"), "campaign.created_at")
    window = require_obj(campaign.get("window"), "campaign.window")
    not_before = parse_utc(
        require_string(window, "not_before", "campaign.window.not_before"),
        "campaign.window.not_before",
    )
    expires_at = parse_utc(
        require_string(window, "expires_at", "campaign.window.expires_at"),
        "campaign.window.expires_at",
    )
    if expires_at <= not_before:
        raise KahnctlError("campaign.window.expires_at must be after not_before")
    if status == "active" and expires_at <= utc_now() and not allow_stale:
        raise KahnctlError(
            "active campaign window is expired; pass --ttl-minutes, --expires-at, "
            "or --allow-stale"
        )

    arena = require_range(campaign.get("arena"), "campaign.arena")
    sizing = require_obj(campaign.get("sizing", {}), "campaign.sizing")
    probe_qty = positive_int(sizing, "probe_quantity", 1, "sizing.probe_quantity")
    add_qty = positive_int(sizing, "add_quantity", 1, "sizing.add_quantity")
    max_qty = positive_int(sizing, "max_position_quantity", 1, "sizing.max_position_quantity")
    if probe_qty > max_qty:
        raise KahnctlError("sizing.probe_quantity must not exceed max_position_quantity")
    if "scale_mode" in sizing:
        scale_mode = require_scale_mode(sizing.get("scale_mode"), "sizing.scale_mode")
    else:
        scale_mode = "scale_allowed" if max_qty > probe_qty else "root_only"
    if scale_mode == "root_only" and max_qty != probe_qty:
        raise KahnctlError(
            "sizing.max_position_quantity must equal probe_quantity when scale_mode is root_only"
        )
    if scale_mode == "scale_allowed" and max_qty <= probe_qty:
        raise KahnctlError(
            "sizing.max_position_quantity must exceed probe_quantity when scale_mode is scale_allowed"
        )

    execution = require_obj(campaign.get("execution", {}), "campaign.execution")
    max_retry = positive_int(execution, "max_retry", 3, "execution.max_retry")

    objective = campaign.get("objective")
    if objective is not None:
        obj = require_obj(objective, "campaign.objective")
        passive = obj.get("passive_harvest")
        if passive is not None:
            ph = require_obj(passive, "campaign.objective.passive_harvest")
            if ph.get("enabled", True):
                if "range" in ph and ph["range"] is not None:
                    require_range(ph["range"], "campaign.objective.passive_harvest.range")
                elif "floor" in ph and "stretch" in ph:
                    require_number(
                        ph,
                        "floor",
                        "campaign.objective.passive_harvest.floor",
                    )
                    require_number(
                        ph,
                        "stretch",
                        "campaign.objective.passive_harvest.stretch",
                    )
                else:
                    raise KahnctlError(
                        "campaign.objective.passive_harvest.range is required when enabled"
                    )

    waypoints = require_list(campaign.get("waypoints"), "campaign.waypoints")
    if not waypoints:
        raise KahnctlError("campaign.waypoints must contain at least one waypoint")

    for index, value in enumerate(waypoints):
        field = f"campaign.waypoints[{index}]"
        waypoint = require_obj(value, field)
        waypoint_id = require_string(waypoint, "id", f"{field}.id")
        if not ID_PATTERN.match(waypoint_id):
            raise KahnctlError(f"{field}.id contains unsupported characters")
        role = require_string(waypoint, "role", f"{field}.role")
        if normalize_role(role) not in {normalize_role(r) for r in SUPPORTED_WAYPOINT_ROLES}:
            raise KahnctlError(f"{field}.role is not supported")
        lower, upper = require_range(waypoint.get("range"), f"{field}.range")
        if upper < arena[0] or lower > arena[1]:
            raise KahnctlError(f"{field}.range must intersect campaign.arena")

    return {
        "id": campaign_id,
        "status": status,
        "side": side,
        "not_before": iso_utc(not_before),
        "expires_at": iso_utc(expires_at),
        "scale_mode": scale_mode,
        "probe_quantity": probe_qty,
        "add_quantity": add_qty,
        "max_position_quantity": max_qty,
        "max_retry": max_retry,
        "waypoint_count": len(waypoints),
    }


def stamp_campaign(args: argparse.Namespace, source: dict[str, Any]) -> dict[str, Any]:
    campaign = copy.deepcopy(source)
    now = utc_now()

    if args.id:
        campaign["id"] = args.id
    elif args.fresh_id:
        prefix = args.id_prefix or "kahn"
        safe_prefix = re.sub(r"[^A-Za-z0-9._:-]+", "-", prefix).strip("-")
        if not safe_prefix:
            safe_prefix = "kahn"
        campaign["id"] = f"{safe_prefix}-{now.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"

    if args.created_now:
        campaign["created_at"] = iso_utc(now)

    if args.activate:
        campaign["status"] = "active"
    elif args.status:
        campaign["status"] = args.status

    window = require_obj(campaign.setdefault("window", {}), "campaign.window")
    not_before = parse_utc(
        require_string(window, "not_before", "campaign.window.not_before"),
        "campaign.window.not_before",
    )
    expires_at = parse_utc(
        require_string(window, "expires_at", "campaign.window.expires_at"),
        "campaign.window.expires_at",
    )

    if args.not_before:
        not_before = parse_utc(args.not_before, "--not-before")
    if args.ttl_minutes is not None:
        if args.ttl_minutes < 1:
            raise KahnctlError("--ttl-minutes must be a positive integer")
        if not args.not_before and args.not_before_now:
            not_before = now
        expires_at = not_before + timedelta(minutes=args.ttl_minutes)
    if args.expires_at:
        expires_at = parse_utc(args.expires_at, "--expires-at")
    window["not_before"] = iso_utc(not_before)
    window["expires_at"] = iso_utc(expires_at)

    sizing = require_obj(campaign.setdefault("sizing", {}), "campaign.sizing")
    if args.probe_qty is not None:
        sizing["probe_quantity"] = args.probe_qty
    if args.add_qty is not None:
        sizing["add_quantity"] = args.add_qty
    if args.max_qty is not None:
        sizing["max_position_quantity"] = args.max_qty
    if args.scale_mode is not None:
        sizing["scale_mode"] = args.scale_mode

    execution = require_obj(campaign.setdefault("execution", {}), "campaign.execution")
    if args.max_retry is not None:
        execution["max_retry"] = args.max_retry

    return campaign


def backup_existing(path: Path) -> str | None:
    if not path.exists():
        return None
    token = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    backup = path.with_name(f"{path.name}.bak.{token}")
    try:
        backup.write_bytes(path.read_bytes())
    except OSError as exc:
        raise KahnctlError(f"failed to back up {path}: {exc}") from exc
    return str(backup)


def archive_acknowledged_control(runtime_dir: Path) -> str | None:
    control_path = runtime_dir / "control.json"
    if not control_path.exists():
        return None

    checkpoint = read_checkpoint_if_present(runtime_dir)
    if not checkpoint:
        return None

    try:
        control = read_json(control_path)
    except KahnctlError:
        return None

    control_id = control.get("id")
    if not (
        control_id
        and control_id == checkpoint.get("last_control_id")
        and checkpoint.get("last_control_status")
    ):
        return None

    token = utc_now().strftime("%Y%m%dT%H%M%S%fZ")
    archive = control_path.with_name(f"{control_path.name}.bak.{token}")
    try:
        control_path.replace(archive)
    except OSError as exc:
        raise KahnctlError(f"failed to archive acknowledged {control_path}: {exc}") from exc
    return str(archive)


def command_validate_draft(args: argparse.Namespace) -> int:
    draft_path = runtime_dir_arg(args.draft)
    campaign = stamp_campaign(args, read_json(draft_path))
    summary = validate_campaign(campaign, allow_stale=args.allow_stale)
    write_result(
        {
            "ok": True,
            "draft_path": str(draft_path),
            "summary": summary,
            "would_write": False,
        }
    )
    return 0


def add_supersession_note(campaign: dict[str, Any], prior: dict[str, Any]) -> None:
    note = (
        f"Supersedes flat {prior['phase']} campaign {prior['id']} "
        f"at {iso_utc(utc_now())}."
    )
    existing = campaign.get("notes")
    campaign["notes"] = f"{existing} {note}" if existing else note


def dispatch_preflight_preview(
    runtime_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any] | None:
    checkpoint = read_checkpoint_if_present(runtime_dir)
    if not checkpoint:
        return None

    active = active_campaign_summary(checkpoint)
    if not active["present"]:
        return None

    phase = checkpoint.get("phase")
    position = position_summary(checkpoint)
    if phase == "Retired":
        action = "would_replace_after_retired"
    elif phase == "Ready" and position["flat"]:
        action = (
            "would_supersede_flat_ready"
            if getattr(args, "retire_existing_if_flat", False)
            else "requires_retire_existing_if_flat"
        )
    else:
        action = "blocked_active_campaign"

    return {
        "id": active["id"],
        "status": active["status"],
        "phase": phase,
        "action": action,
    }


def prepare_campaign_dispatch(
    runtime_dir: Path,
    campaign: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any] | None:
    if getattr(args, "dry_run", False):
        return None

    checkpoint = read_checkpoint_if_present(runtime_dir)
    if not checkpoint:
        return None

    active = active_campaign_summary(checkpoint)
    if not active["present"]:
        return None

    phase = checkpoint.get("phase")
    position = position_summary(checkpoint)
    assessment = preflight_assessment(
        runtime_dir,
        checkpoint,
        checkpoint_stale_seconds=max(0, getattr(args, "preflight_stale_seconds", 15)),
        control_stale_seconds=max(0, getattr(args, "control_stale_seconds", 60)),
    )
    preflight_safe = (
        assessment["runtime_running"]
        and assessment["checkpoint_fresh"]
        and assessment["correct_paths"]
        and not assessment["stale_control_file"]
        and assessment["position"]["flat"]
    )
    if phase == "Retired":
        if not preflight_safe:
            raise KahnctlError(
                "cannot replace retired campaign: preflight is not safe"
            )
        return {
            "id": active["id"],
            "status": active["status"],
            "phase": phase,
            "action": "replaced_after_retired",
        }

    flat_ready = phase == "Ready" and position["flat"]
    if not flat_ready:
        raise KahnctlError(
            f"refusing to replace active campaign {active['id']} in phase {phase}; "
            "use FLAT/CANCEL or wait for Retired before dispatch"
        )

    if not getattr(args, "retire_existing_if_flat", False):
        raise KahnctlError(
            f"active campaign {active['id']} is flat/Ready; pass "
            "--retire-existing-if-flat to supersede it cleanly"
        )

    if not preflight_safe:
        raise KahnctlError(
            "cannot supersede active flat/Ready campaign: preflight is not safe"
        )

    prior = {
        "id": active["id"],
        "status": active["status"],
        "phase": phase,
        "action": "superseded_flat_ready",
    }
    add_supersession_note(campaign, prior)
    return prior


def command_dispatch_draft(args: argparse.Namespace) -> int:
    profile, runtime_dir, custom = select_runtime(args)
    draft_path = runtime_dir_arg(args.draft)
    campaign = stamp_campaign(args, read_json(draft_path))
    summary = validate_campaign(campaign, allow_stale=args.allow_stale)
    target = runtime_dir / "campaign.json"

    if args.dry_run:
        prior = dispatch_preflight_preview(runtime_dir, args)
        write_result(
            {
                "ok": True,
                "dry_run": True,
                "profile": profile,
                "custom": custom,
                "runtime_dir": str(runtime_dir),
                "draft_path": str(draft_path),
                "campaign_path": str(target),
                "prior_campaign": prior,
                "summary": summary,
            }
        )
        return 0

    prior = prepare_campaign_dispatch(runtime_dir, campaign, args)
    backup = None if args.no_backup else backup_existing(target)
    control_backup = archive_acknowledged_control(runtime_dir)
    atomic_write(target, campaign, sort_keys=False)
    write_result(
        {
            "ok": True,
            "profile": profile,
            "custom": custom,
            "runtime_dir": str(runtime_dir),
            "draft_path": str(draft_path),
            "campaign_path": str(target),
            "backup_path": backup,
            "control_backup_path": control_backup,
            "prior_campaign": prior,
            "summary": summary,
        }
    )
    return 0


def read_optional_text(text: str | None, path_text: str | None, field: str) -> str | None:
    if text and path_text:
        raise KahnctlError(f"use either --{field} or --{field}-file, not both")
    if text:
        return text
    if not path_text:
        return None

    path = runtime_dir_arg(path_text)
    try:
        return path.read_text(encoding="utf-8-sig").strip()
    except FileNotFoundError as exc:
        raise KahnctlError(f"{path} not found") from exc
    except OSError as exc:
        raise KahnctlError(f"failed to read {path}: {exc}") from exc


def command_new_draft(args: argparse.Namespace) -> int:
    profile, runtime_dir, custom = select_runtime(args)
    if args.dispatch and profile == "DEFAULT" and not custom and not args.force_default_profile:
        raise KahnctlError(
            "refusing to dispatch to DEFAULT profile; pass ES/NQ, --runtime-dir, "
            "or --force-default-profile"
        )

    now = utc_now()
    created_at = parse_utc(args.created_at, "--created-at") if args.created_at else now
    not_before = parse_utc(args.not_before, "--not-before") if args.not_before else now
    if args.expires_at:
        expires_at = parse_utc(args.expires_at, "--expires-at")
    else:
        if args.ttl_minutes < 1:
            raise KahnctlError("--ttl-minutes must be a positive integer")
        expires_at = not_before + timedelta(minutes=args.ttl_minutes)

    status = "active" if args.activate else args.status
    role_ranges = {
        "trap_probe": args.probe,
        "press": args.press,
        "build_trial": args.build_trial,
        "evaluate": args.evaluate,
        "no_add": args.no_add,
        "path_stress": args.path_stress,
        "target": args.target_waypoint,
        "repair_hold": args.repair_hold,
        "risk": args.risk,
        "invalidation": args.invalidation,
    }
    harvest_initial = args.harvest_initial_qty or 1
    harvest_follow = args.harvest_follow_qty or harvest_initial
    harvest_working = args.harvest_working_qty or max(harvest_initial, harvest_follow)
    notes = read_optional_text(args.notes, args.notes_file, "notes")

    campaign = build_campaign(
        profile=profile.lower(),
        side=args.side,
        status=status,
        campaign_id=args.id,
        id_prefix=args.id_prefix,
        created_at=created_at,
        not_before=not_before,
        expires_at=expires_at,
        arena=args.arena,
        role_ranges=role_ranges,
        generic_waypoints=args.waypoint,
        target_range=args.target,
        include_target_waypoint=not args.no_target_waypoint,
        passive_harvest_range=args.passive_harvest,
        scale_mode=args.scale_mode,
        probe_quantity=args.probe_qty,
        add_quantity=args.add_qty,
        max_position_quantity=args.max_qty,
        max_retry=args.max_retry,
        root_stop_ticks=args.root_stop_ticks,
        sponsor_failure_buffer_ticks=args.sponsor_failure_buffer_ticks,
        allow_contest_beyond_risk_anchor=args.allow_contest_beyond_risk_anchor,
        target_proximity_ticks=args.target_proximity_ticks,
        suppress_adds_in_target_zone=args.suppress_adds_in_target_zone,
        harvest_initial_quantity=harvest_initial,
        harvest_follow_quantity=harvest_follow,
        harvest_max_working_quantity=harvest_working,
        harvest_floor_failure_ticks=args.harvest_floor_failure_ticks,
        probe_requires_inside=args.probe_requires_inside,
        press_requires_inside=args.press_requires_inside,
        press_preserves_root=args.press_preserves_root,
        path_stress_max_qty=args.path_stress_max_qty,
        notes=notes,
    )
    summary = validate_campaign(campaign, allow_stale=args.allow_stale)

    out_path = runtime_dir_arg(args.out) if args.out else None
    dispatch_path = runtime_dir / "campaign.json" if args.dispatch else None
    backup = None
    control_backup = None
    prior = dispatch_preflight_preview(runtime_dir, args) if args.dispatch else None
    if not args.dry_run:
        if dispatch_path:
            prior = prepare_campaign_dispatch(runtime_dir, campaign, args)
        if out_path:
            atomic_write(out_path, campaign, sort_keys=False)
        if dispatch_path:
            backup = None if args.no_backup else backup_existing(dispatch_path)
            control_backup = archive_acknowledged_control(runtime_dir)
            atomic_write(dispatch_path, campaign, sort_keys=False)

    payload: dict[str, Any] = {
        "ok": True,
        "dry_run": args.dry_run,
        "profile": profile,
        "custom": custom,
        "runtime_dir": str(runtime_dir),
        "out_path": str(out_path) if out_path else None,
        "campaign_path": str(dispatch_path) if dispatch_path else None,
        "backup_path": backup,
        "control_backup_path": control_backup,
        "prior_campaign": prior,
        "summary": summary,
    }
    if not args.summary_only:
        payload["campaign"] = campaign
    write_result(payload)
    return 0


def add_profile_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "profile",
        nargs="?",
        default=None,
        help="Named runtime profile (ES, NQ, DEFAULT) or an explicit runtime directory.",
    )
    parser.add_argument(
        "--runtime-dir",
        default=None,
        help="Explicit Kahn runtime directory. Overrides the profile positional.",
    )


def add_stamp_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--activate", action="store_true", help="Set campaign.status=active.")
    parser.add_argument("--status", choices=["active", "draft"], default=None)
    parser.add_argument("--id", default=None, help="Override campaign.id.")
    parser.add_argument("--fresh-id", action="store_true", help="Generate a fresh campaign id.")
    parser.add_argument("--id-prefix", default=None, help="Prefix used with --fresh-id.")
    parser.add_argument("--created-now", action="store_true", help="Set created_at to now.")
    parser.add_argument("--not-before", default=None, help="Override window.not_before.")
    parser.add_argument(
        "--not-before-now",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="With --ttl-minutes, start the window at now unless --not-before is set.",
    )
    parser.add_argument("--expires-at", default=None, help="Override window.expires_at.")
    parser.add_argument("--ttl-minutes", type=int, default=None, help="Set expires_at from not_before.")
    parser.add_argument(
        "--scale-mode",
        type=scale_mode_arg,
        default=None,
        help="Set sizing.scale_mode to root_only or scale_allowed.",
    )
    parser.add_argument("--probe-qty", type=int, default=None)
    parser.add_argument("--add-qty", type=int, default=None)
    parser.add_argument("--max-qty", type=int, default=None)
    parser.add_argument("--max-retry", type=int, default=None)
    parser.add_argument("--allow-stale", action="store_true", help="Allow active expired campaign windows.")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Operate KahnRuntime profile paths, controls, and campaign drafts."
    )
    p.add_argument(
        "--runtime-dir",
        dest="global_runtime_dir",
        default=None,
        help="Backward-compatible global runtime dir override.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    profiles = sub.add_parser("profiles", help="List built-in runtime profiles.")
    profiles.set_defaults(func=command_profiles)

    paths = sub.add_parser("paths", help="Print Quantower path settings for a runtime profile.")
    add_profile_argument(paths)
    paths.set_defaults(func=command_paths)

    preflight = sub.add_parser("preflight", help="Print a terse Kahn dispatch/control readiness gate.")
    add_profile_argument(preflight)
    preflight.add_argument(
        "--stale-seconds",
        type=int,
        default=15,
        help="Checkpoint freshness threshold.",
    )
    preflight.add_argument(
        "--control-stale-seconds",
        type=int,
        default=60,
        help="Unprocessed control file age threshold.",
    )
    preflight.set_defaults(func=command_preflight)

    for name, action, help_text in (
        ("flat", "FLAT", "Cancel Kahn-owned working orders, close bound position(s), and retire the campaign."),
        ("flatten", "FLAT", "Alias for flat."),
        ("cancel", "CANCEL", "Cancel/retire the campaign only when the bound position is flat."),
    ):
        cmd = sub.add_parser(name, help=help_text)
        add_profile_argument(cmd)
        cmd.add_argument("--reason", default=None)
        cmd.add_argument(
            "--force-shared-control",
            action="store_true",
            help="Allow writing the legacy root control.json.",
        )
        cmd.set_defaults(func=command_control, action=action)

    status = sub.add_parser("status", help="Read Kahn checkpoint summary.")
    add_profile_argument(status)
    status.add_argument(
        "--stale-seconds",
        type=int,
        default=15,
        help="Warn when checkpoint.updated_utc is older than this many seconds.",
    )
    status.set_defaults(func=command_status)

    validate = sub.add_parser("validate-draft", help="Validate a draft campaign without writing it.")
    validate.add_argument("--draft", required=True, help="Path to a KAHN_CAMPAIGN draft JSON file.")
    add_stamp_arguments(validate)
    validate.set_defaults(func=command_validate_draft)

    dispatch = sub.add_parser("dispatch-draft", help="Stamp and write a draft to profile campaign.json.")
    add_profile_argument(dispatch)
    dispatch.add_argument("--draft", required=True, help="Path to a KAHN_CAMPAIGN draft JSON file.")
    dispatch.add_argument("--dry-run", action="store_true", help="Validate and show target without writing.")
    dispatch.add_argument("--no-backup", action="store_true", help="Do not back up existing campaign.json.")
    dispatch.add_argument(
        "--retire-existing-if-flat",
        action="store_true",
        help="Allow superseding an active flat/Ready campaign after safe preflight.",
    )
    dispatch.add_argument(
        "--preflight-stale-seconds",
        type=int,
        default=15,
        help="Checkpoint freshness required by --retire-existing-if-flat.",
    )
    dispatch.add_argument(
        "--control-stale-seconds",
        type=int,
        default=60,
        help="Control-file freshness required by --retire-existing-if-flat.",
    )
    add_stamp_arguments(dispatch)
    dispatch.set_defaults(func=command_dispatch_draft)

    new_draft = sub.add_parser("new-draft", help="Assemble KAHN_CAMPAIGN JSON from compact ranges.")
    add_profile_argument(new_draft)
    new_draft.add_argument("--side", required=True, choices=["long", "short"])
    new_draft.add_argument("--arena", required=True, help="Campaign arena as LOWER:UPPER.")
    new_draft.add_argument("--status", choices=["active", "draft"], default="draft")
    new_draft.add_argument("--activate", action="store_true", help="Set campaign.status=active.")
    new_draft.add_argument("--id", default=None, help="Explicit campaign id.")
    new_draft.add_argument("--id-prefix", default=None, help="Prefix for generated campaign id.")
    new_draft.add_argument("--created-at", default=None, help="Override created_at; defaults to now.")
    new_draft.add_argument("--not-before", default=None, help="Override window.not_before; defaults to now.")
    new_draft.add_argument("--expires-at", default=None, help="Override window.expires_at.")
    new_draft.add_argument("--ttl-minutes", type=int, default=30, help="Expiry offset when --expires-at is omitted.")
    new_draft.add_argument(
        "--scale-mode",
        type=scale_mode_arg,
        default="root_only",
        help="Scaling intent: root_only blocks leverage; scale_allowed discovers adds from repaired-continuation evidence.",
    )
    new_draft.add_argument("--probe-qty", type=int, default=1)
    new_draft.add_argument("--add-qty", type=int, default=1)
    new_draft.add_argument("--max-qty", type=int, default=1)
    new_draft.add_argument("--max-retry", type=int, default=3)
    new_draft.add_argument("--root-stop-ticks", type=int, default=16)
    new_draft.add_argument("--sponsor-failure-buffer-ticks", type=int, default=2)
    new_draft.add_argument(
        "--allow-contest-beyond-risk-anchor",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    new_draft.add_argument("--target", default=None, help="Objective target range as LOWER:UPPER.")
    new_draft.add_argument("--target-proximity-ticks", type=int, default=8)
    new_draft.add_argument(
        "--suppress-adds-in-target-zone",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    new_draft.add_argument(
        "--no-target-waypoint",
        action="store_true",
        help="Do not mirror --target into a target waypoint.",
    )
    new_draft.add_argument("--passive-harvest", default=None, help="Passive harvest range as LOWER:UPPER.")
    new_draft.add_argument("--harvest-initial-qty", type=int, default=None)
    new_draft.add_argument("--harvest-follow-qty", type=int, default=None)
    new_draft.add_argument("--harvest-working-qty", type=int, default=None)
    new_draft.add_argument("--harvest-floor-failure-ticks", type=int, default=0)
    new_draft.add_argument("--probe", action="append", default=[], help="Trap-probe range; repeatable.")
    new_draft.add_argument("--press", action="append", default=[], help="Press range; repeatable.")
    new_draft.add_argument(
        "--build",
        "--build-trial",
        dest="build_trial",
        action="append",
        default=[],
        help="Build-trial range; repeatable.",
    )
    new_draft.add_argument("--evaluate", action="append", default=[], help="Evaluate range; repeatable.")
    new_draft.add_argument("--no-add", action="append", default=[], help="No-add range; repeatable.")
    new_draft.add_argument("--path-stress", action="append", default=[], help="Path-stress range; repeatable.")
    new_draft.add_argument("--path-stress-max-qty", type=int, default=None)
    new_draft.add_argument("--target-waypoint", action="append", default=[], help="Additional target waypoint range.")
    new_draft.add_argument("--repair-hold", action="append", default=[], help="Repair-hold range; repeatable.")
    new_draft.add_argument("--risk", action="append", default=[], help="Risk review range; repeatable.")
    new_draft.add_argument(
        "--wrong",
        "--invalidation",
        dest="invalidation",
        action="append",
        default=[],
        help="Invalidation range; repeatable.",
    )
    new_draft.add_argument(
        "--waypoint",
        action="append",
        default=[],
        help="Generic waypoint as role:LOWER:UPPER or role:ID:LOWER:UPPER.",
    )
    new_draft.add_argument(
        "--probe-requires-inside",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    new_draft.add_argument(
        "--press-requires-inside",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    new_draft.add_argument(
        "--press-preserves-root",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    new_draft.add_argument("--notes", default=None)
    new_draft.add_argument("--notes-file", default=None)
    new_draft.add_argument("--out", default=None, help="Optional draft JSON output path.")
    new_draft.add_argument("--dispatch", action="store_true", help="Write directly to profile campaign.json.")
    new_draft.add_argument("--dry-run", action="store_true", help="Validate and print without writing.")
    new_draft.add_argument("--no-backup", action="store_true", help="Do not back up campaign.json when dispatching.")
    new_draft.add_argument(
        "--retire-existing-if-flat",
        action="store_true",
        help="Allow superseding an active flat/Ready campaign after safe preflight.",
    )
    new_draft.add_argument(
        "--preflight-stale-seconds",
        type=int,
        default=15,
        help="Checkpoint freshness required by --retire-existing-if-flat.",
    )
    new_draft.add_argument(
        "--control-stale-seconds",
        type=int,
        default=60,
        help="Control-file freshness required by --retire-existing-if-flat.",
    )
    new_draft.add_argument(
        "--force-default-profile",
        action="store_true",
        help="Allow direct dispatch to the legacy DEFAULT runtime profile.",
    )
    new_draft.add_argument("--allow-stale", action="store_true", help="Allow active expired campaign windows.")
    new_draft.add_argument("--summary-only", action="store_true", help="Omit full campaign JSON from output.")
    new_draft.set_defaults(func=command_new_draft)

    return p


def main() -> int:
    try:
        args = parser().parse_args()
        return args.func(args)
    except (KahnctlError, CampaignAssemblyError) as exc:
        write_result({"ok": False, "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
