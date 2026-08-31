#!/usr/bin/env python3
"""Kahn campaign JSON assembly helpers.

The assembler owns the mechanical KAHN_CAMPAIGN shape. Saavik still owns the
auction judgment: side, ranges, roles, notes, and whether a campaign should be
armed at all.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from uuid import uuid4


class CampaignAssemblyError(Exception):
    """User-facing campaign assembly error."""


ROLE_ALIASES = {
    "probe": "trap_probe",
    "trapprobe": "trap_probe",
    "trap_probe": "trap_probe",
    "press": "press",
    "build": "build_trial",
    "buildtrial": "build_trial",
    "build_trial": "build_trial",
    "target": "target",
    "noadd": "no_add",
    "no_add": "no_add",
    "evaluate": "evaluate",
    "risk": "risk",
    "repairhold": "repair_hold",
    "repair_hold": "repair_hold",
    "pathstress": "path_stress",
    "path_stress": "path_stress",
    "maturepath": "path_stress",
    "mature_path": "path_stress",
    "wrong": "invalidation",
    "invalid": "invalidation",
    "invalidation": "invalidation",
}

SCALE_MODE_ALIASES = {
    "scaleallowed": "scale_allowed",
    "scalingallowed": "scale_allowed",
    "evidencescaled": "scale_allowed",
    "evidence": "scale_allowed",
    "allowed": "scale_allowed",
    "rootonly": "root_only",
    "noscaling": "root_only",
    "noadd": "root_only",
    "disabled": "root_only",
    "off": "root_only",
}

ROLE_ORDER = (
    "trap_probe",
    "press",
    "build_trial",
    "evaluate",
    "no_add",
    "path_stress",
    "target",
    "repair_hold",
    "risk",
    "invalidation",
)

ROLE_ID_PREFIX = {
    "trap_probe": "probe",
    "press": "press",
    "build_trial": "build",
    "evaluate": "evaluate",
    "no_add": "no-add",
    "path_stress": "pathstress",
    "target": "target",
    "repair_hold": "repair-hold",
    "risk": "risk",
    "invalidation": "wrong",
}

ROLE_LABEL = {
    "trap_probe": "{side} trap probe in {price_range}; require matching campaign evidence.",
    "press": "{side} press zone in {price_range}; require same-side sponsorship.",
    "build_trial": "{side} build trial in {price_range}; sponsor must accept the move.",
    "evaluate": "Evaluate campaign quality in {price_range}; suppress leverage while reading.",
    "no_add": "No-add corridor in {price_range}; hold is allowed but leverage is locked.",
    "path_stress": "Mature path stress in {price_range}; harvest or cut size if reward slows.",
    "target": "Campaign objective in {price_range}.",
    "repair_hold": "Repair-hold zone in {price_range}; preserve root risk unless sponsor fails.",
    "risk": "Risk review zone in {price_range}.",
    "invalidation": "Campaign invalidation area in {price_range}.",
}


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_role(value: str) -> str:
    return (value or "").replace("-", "").replace("_", "").replace(" ", "").lower()


def canonical_role(value: str) -> str:
    key = normalize_role(value)
    role = ROLE_ALIASES.get(key)
    if not role:
        known = ", ".join(ROLE_ORDER)
        raise CampaignAssemblyError(f"unsupported waypoint role {value!r}; use one of {known}")
    return role


def canonical_scale_mode(value: str | None) -> str:
    key = normalize_role(value or "")
    mode = SCALE_MODE_ALIASES.get(key)
    if not mode:
        raise CampaignAssemblyError("--scale-mode must be root_only or scale_allowed")
    return mode


def parse_range_spec(value: str, field: str = "range") -> dict[str, float]:
    text = (value or "").strip()
    if not text:
        raise CampaignAssemblyError(f"{field} must be LOWER:UPPER")

    for separator in ("..", ","):
        text = text.replace(separator, ":")
    pieces = [part.strip() for part in text.split(":") if part.strip()]
    if len(pieces) != 2:
        raise CampaignAssemblyError(f"{field} must be LOWER:UPPER")

    try:
        lower = float(pieces[0])
        upper = float(pieces[1])
    except ValueError as exc:
        raise CampaignAssemblyError(f"{field} bounds must be numeric") from exc
    if not math.isfinite(lower) or not math.isfinite(upper):
        raise CampaignAssemblyError(f"{field} bounds must be finite")
    if lower > upper:
        lower, upper = upper, lower
    return {"lower": normalize_price(lower), "upper": normalize_price(upper)}


def parse_generic_waypoint(value: str) -> dict[str, Any]:
    pieces = [part.strip() for part in (value or "").split(":") if part.strip()]
    if len(pieces) == 3:
        role_text, lower, upper = pieces
        waypoint_id = None
    elif len(pieces) == 4:
        role_text, waypoint_id, lower, upper = pieces
    else:
        raise CampaignAssemblyError(
            "--waypoint must be role:LOWER:UPPER or role:ID:LOWER:UPPER"
        )
    return {
        "role": canonical_role(role_text),
        "id": waypoint_id,
        "range": parse_range_spec(f"{lower}:{upper}", "--waypoint range"),
    }


def normalize_price(value: float) -> int | float:
    if float(value).is_integer():
        return int(value)
    return float(value)


def price_text(value: int | float) -> str:
    text = f"{float(value):.8f}".rstrip("0").rstrip(".")
    return text.replace("-", "m").replace(".", "p")


def display_range(price_range: Mapping[str, int | float]) -> str:
    return f"{price_range['lower']}-{price_range['upper']}"


def fresh_campaign_id(profile: str, side: str, prefix: str | None, now: datetime) -> str:
    base = prefix or f"{profile.lower()}-{side.lower()}-campaign"
    safe = re.sub(r"[^A-Za-z0-9._:-]+", "-", base).strip("-")
    if not safe:
        safe = "kahn-campaign"
    return f"{safe}-{now.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"


def generated_waypoint_id(
    role: str,
    price_range: Mapping[str, int | float],
    used: set[str],
) -> str:
    prefix = ROLE_ID_PREFIX[role]
    base = f"{prefix}-{price_text(price_range['lower'])}-{price_text(price_range['upper'])}"
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}-{index}"
        index += 1
    used.add(candidate)
    return candidate


def default_label(role: str, side: str, price_range: Mapping[str, int | float]) -> str:
    return ROLE_LABEL[role].format(
        side=side.title(),
        price_range=display_range(price_range),
    )


def waypoint(
    role: str,
    price_range: Mapping[str, int | float],
    *,
    waypoint_id: str | None,
    side: str,
    used_ids: set[str],
    probe_requires_inside: bool,
    press_requires_inside: bool,
    press_preserves_root: bool,
    path_stress_max_qty: int | None,
) -> dict[str, Any]:
    canonical = canonical_role(role)
    result: dict[str, Any] = {
        "id": waypoint_id
        or generated_waypoint_id(canonical, price_range, used_ids),
        "role": canonical,
        "range": dict(price_range),
        "label": default_label(canonical, side, price_range),
    }
    if waypoint_id:
        if waypoint_id in used_ids:
            raise CampaignAssemblyError(f"duplicate waypoint id {waypoint_id}")
        used_ids.add(waypoint_id)
    if canonical == "trap_probe" and probe_requires_inside:
        result["require_price_inside"] = True
    if canonical == "press":
        if press_requires_inside:
            result["require_price_inside"] = True
        if press_preserves_root:
            result["preserve_risk_anchor_on_add"] = True
    if canonical == "path_stress" and path_stress_max_qty is not None:
        result["max_position_quantity"] = path_stress_max_qty
    return result


def collect_waypoints(
    role_ranges: Mapping[str, Iterable[str]],
    generic_specs: Iterable[str],
    *,
    side: str,
    target_range: str | None,
    include_target_waypoint: bool,
    probe_requires_inside: bool,
    press_requires_inside: bool,
    press_preserves_root: bool,
    path_stress_max_qty: int | None,
) -> list[dict[str, Any]]:
    parsed: dict[str, list[dict[str, Any]]] = {role: [] for role in ROLE_ORDER}

    for role_text, ranges in role_ranges.items():
        role = canonical_role(role_text)
        for range_text in ranges:
            parsed[role].append(
                {
                    "role": role,
                    "id": None,
                    "range": parse_range_spec(range_text, f"--{role.replace('_', '-')}"),
                }
            )

    if target_range and include_target_waypoint:
        parsed["target"].append(
            {
                "role": "target",
                "id": None,
                "range": parse_range_spec(target_range, "--target"),
            }
        )

    for spec in generic_specs:
        item = parse_generic_waypoint(spec)
        parsed[item["role"]].append(item)

    used_ids: set[str] = set()
    result: list[dict[str, Any]] = []
    for role in ROLE_ORDER:
        for item in parsed[role]:
            result.append(
                waypoint(
                    role,
                    item["range"],
                    waypoint_id=item["id"],
                    side=side,
                    used_ids=used_ids,
                    probe_requires_inside=probe_requires_inside,
                    press_requires_inside=press_requires_inside,
                    press_preserves_root=press_preserves_root,
                    path_stress_max_qty=path_stress_max_qty,
                )
            )
    if not result:
        raise CampaignAssemblyError("at least one waypoint or --target is required")
    return result


def build_campaign(
    *,
    profile: str,
    side: str,
    status: str,
    campaign_id: str | None,
    id_prefix: str | None,
    created_at: datetime,
    not_before: datetime,
    expires_at: datetime,
    arena: str,
    role_ranges: Mapping[str, Iterable[str]],
    generic_waypoints: Iterable[str],
    target_range: str | None,
    include_target_waypoint: bool,
    passive_harvest_range: str | None,
    scale_mode: str,
    probe_quantity: int,
    add_quantity: int,
    max_position_quantity: int,
    max_retry: int,
    root_stop_ticks: int,
    sponsor_failure_buffer_ticks: int,
    allow_contest_beyond_risk_anchor: bool,
    target_proximity_ticks: int,
    suppress_adds_in_target_zone: bool,
    harvest_initial_quantity: int,
    harvest_follow_quantity: int,
    harvest_max_working_quantity: int,
    harvest_floor_failure_ticks: int,
    probe_requires_inside: bool,
    press_requires_inside: bool,
    press_preserves_root: bool,
    path_stress_max_qty: int | None,
    notes: str | None,
) -> dict[str, Any]:
    side_text = side.lower()
    if side_text not in {"long", "short"}:
        raise CampaignAssemblyError("--side must be long or short")
    if status not in {"active", "draft"}:
        raise CampaignAssemblyError("--status must be active or draft")
    if expires_at <= not_before:
        raise CampaignAssemblyError("expires_at must be after not_before")
    for field, value in (
        ("--probe-qty", probe_quantity),
        ("--add-qty", add_quantity),
        ("--max-qty", max_position_quantity),
        ("--max-retry", max_retry),
        ("--root-stop-ticks", root_stop_ticks),
        ("--sponsor-failure-buffer-ticks", sponsor_failure_buffer_ticks),
        ("--target-proximity-ticks", target_proximity_ticks),
        ("--harvest-initial-qty", harvest_initial_quantity),
        ("--harvest-follow-qty", harvest_follow_quantity),
        ("--harvest-working-qty", harvest_max_working_quantity),
    ):
        if value < 1:
            raise CampaignAssemblyError(f"{field} must be a positive integer")
    if harvest_floor_failure_ticks < 0:
        raise CampaignAssemblyError("--harvest-floor-failure-ticks must be non-negative")
    if path_stress_max_qty is not None and path_stress_max_qty < 1:
        raise CampaignAssemblyError("--path-stress-max-qty must be a positive integer")
    if probe_quantity > max_position_quantity:
        raise CampaignAssemblyError("--probe-qty must not exceed --max-qty")
    scale_mode_text = canonical_scale_mode(scale_mode)
    if scale_mode_text == "root_only" and max_position_quantity != probe_quantity:
        raise CampaignAssemblyError("--max-qty must equal --probe-qty when --scale-mode root_only")
    if scale_mode_text == "scale_allowed" and max_position_quantity <= probe_quantity:
        raise CampaignAssemblyError("--max-qty must exceed --probe-qty when --scale-mode scale_allowed")

    campaign = {
        "schema_version": 1,
        "kind": "KAHN_CAMPAIGN",
        "id": campaign_id
        or fresh_campaign_id(profile, side_text, id_prefix, created_at),
        "status": status,
        "created_at": iso_utc(created_at),
        "side": side_text,
        "window": {
            "not_before": iso_utc(not_before),
            "expires_at": iso_utc(expires_at),
        },
        "arena": parse_range_spec(arena, "--arena"),
        "sizing": {
            "scale_mode": scale_mode_text,
            "probe_quantity": probe_quantity,
            "add_quantity": add_quantity,
            "max_position_quantity": max_position_quantity,
        },
        "execution": {
            "max_retry": max_retry,
        },
        "risk": {
            "root_stop_ticks": root_stop_ticks,
            "sponsor_failure_buffer_ticks": sponsor_failure_buffer_ticks,
            "allow_contest_beyond_risk_anchor": allow_contest_beyond_risk_anchor,
        },
    }

    objective: dict[str, Any] = {}
    if target_range:
        objective["target_range"] = parse_range_spec(target_range, "--target")
        objective["target_proximity_ticks"] = target_proximity_ticks
        objective["suppress_adds_in_target_zone"] = suppress_adds_in_target_zone
    if passive_harvest_range:
        objective["passive_harvest"] = {
            "range": parse_range_spec(passive_harvest_range, "--passive-harvest"),
            "initial_clip_quantity": harvest_initial_quantity,
            "follow_clip_quantity": harvest_follow_quantity,
            "max_working_quantity": harvest_max_working_quantity,
            "floor_failure_ticks": harvest_floor_failure_ticks,
        }
    if objective:
        campaign["objective"] = objective

    campaign["waypoints"] = collect_waypoints(
        role_ranges,
        generic_waypoints,
        side=side_text,
        target_range=target_range,
        include_target_waypoint=include_target_waypoint,
        probe_requires_inside=probe_requires_inside,
        press_requires_inside=press_requires_inside,
        press_preserves_root=press_preserves_root,
        path_stress_max_qty=path_stress_max_qty,
    )

    if notes:
        campaign["notes"] = notes
    return campaign
