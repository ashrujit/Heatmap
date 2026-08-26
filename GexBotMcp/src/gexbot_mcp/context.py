"""Normalization helpers for decision-facing GexBot context."""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any


LEVEL_FIELDS = (
    ("zero_gamma", "zero_gamma", "Gamma flip / regime boundary"),
    ("major_pos_vol", "positive_gex_volume", "Largest positive GEX by volume"),
    ("mpos_vol", "positive_gex_volume", "Largest positive GEX by volume"),
    ("major_pos_oi", "positive_gex_oi", "Largest positive GEX by open interest"),
    ("mpos_oi", "positive_gex_oi", "Largest positive GEX by open interest"),
    ("major_neg_vol", "negative_gex_volume", "Largest negative GEX by volume"),
    ("mneg_vol", "negative_gex_volume", "Largest negative GEX by volume"),
    ("major_neg_oi", "negative_gex_oi", "Largest negative GEX by open interest"),
    ("mneg_oi", "negative_gex_oi", "Largest negative GEX by open interest"),
    ("major_long_gamma", "long_gamma", "Largest long-gamma state level"),
    ("major_short_gamma", "short_gamma", "Largest short-gamma state level"),
)


def build_decision_context(
    payload: dict[str, Any],
    *,
    package: str,
    category: str,
    center_price: float | None = None,
    radius_points: float | None = None,
    max_strikes: int = 16,
    tick_size: float = 0.25,
    zone_ticks: int = 8,
) -> dict[str, Any]:
    """Return the normalized shape that Prep, Saavik, or Kahn can reason over."""

    spot = _number(payload.get("spot"))
    center = _number(center_price) if center_price is not None else spot
    timestamp = _timestamp(payload.get("timestamp"))
    markers = _level_markers(payload, tick_size=tick_size, zone_ticks=zone_ticks)
    strikes = _nearby_strikes(
        payload.get("strikes"),
        center_price=center,
        radius_points=radius_points,
        max_strikes=max_strikes,
    )
    sum_gex_oi = _number(payload.get("sum_gex_oi"))
    sum_gex_vol = _number(payload.get("sum_gex_vol"))

    return {
        "ok": True,
        "ticker": payload.get("ticker"),
        "package": package,
        "category": category,
        "timestamp": payload.get("timestamp"),
        "as_of_utc": timestamp,
        "spot": spot,
        "min_dte": payload.get("min_dte"),
        "sec_min_dte": payload.get("sec_min_dte"),
        "regime_hint": _regime_hint(sum_gex_oi=sum_gex_oi, sum_gex_vol=sum_gex_vol),
        "major_levels": markers,
        "nearby_strikes": strikes,
        "aggregates": {
            "sum_gex_oi": sum_gex_oi,
            "sum_gex_vol": sum_gex_vol,
            "delta_risk_reversal": _number(payload.get("delta_risk_reversal")),
        },
        "decision_boundary": {
            "usable_for": [
                "option-location context",
                "volatility and path-stress awareness",
                "Prep/Saavik branch or checkpoint refinement",
                "Kahn waypoint proposals after a user-declared campaign",
            ],
            "not_usable_for": [
                "trade permission",
                "auction acceptance proof",
                "sponsorship proof",
                "Kahn entry/add authorization by itself",
            ],
        },
        "kahn_mapping": _kahn_mapping(markers),
        "schema_notes": [
            "Raw GexBot fields are preserved separately by gexbot_snapshot.",
            "Strike rows are interpreted as [strike, gex_by_volume, gex_by_oi, priors] from the public response example.",
            "Use ES_SPX/NQ_NDX for futures price-space context when available.",
        ],
    }


def snapshot_summary(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"type": type(payload).__name__}
    return {
        "ticker": payload.get("ticker"),
        "timestamp": payload.get("timestamp"),
        "as_of_utc": _timestamp(payload.get("timestamp")),
        "spot": _number(payload.get("spot")),
        "keys": sorted(str(key) for key in payload.keys()),
        "strike_count": len(payload.get("strikes") or []),
    }


def _level_markers(payload: dict[str, Any], *, tick_size: float, zone_ticks: int) -> list[dict[str, Any]]:
    seen: set[tuple[str, float]] = set()
    markers: list[dict[str, Any]] = []
    for field, role, label in LEVEL_FIELDS:
        price = _number(payload.get(field))
        if price is None:
            continue
        key = (role, price)
        if key in seen:
            continue
        seen.add(key)
        markers.append(
            {
                "role": role,
                "price": price,
                "range": _zone(price, tick_size=tick_size, zone_ticks=zone_ticks),
                "source_field": field,
                "label": label,
                "kahn_role_bias": _kahn_role_bias(role),
            }
        )
    return markers


def _nearby_strikes(
    rows: Any,
    *,
    center_price: float | None,
    radius_points: float | None,
    max_strikes: int,
) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []

    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list) or not row:
            continue
        strike = _number(row[0])
        if strike is None:
            continue
        gex_volume = _number(row[1]) if len(row) > 1 else None
        gex_oi = _number(row[2]) if len(row) > 2 else None
        if center_price is not None and radius_points is not None:
            if abs(strike - center_price) > max(0.0, radius_points):
                continue
        parsed.append(
            {
                "strike": strike,
                "distance": None if center_price is None else strike - center_price,
                "gex_volume": gex_volume,
                "gex_oi": gex_oi,
                "abs_gex_oi": abs(gex_oi) if gex_oi is not None else None,
                "raw_width": len(row),
            }
        )

    if center_price is not None:
        parsed.sort(key=lambda item: (abs(item["distance"]), item["strike"]))
    else:
        parsed.sort(
            key=lambda item: (
                -(item["abs_gex_oi"] or 0.0),
                item["strike"],
            )
        )
    return parsed[: max(0, max_strikes)]


def _kahn_mapping(markers: list[dict[str, Any]]) -> dict[str, Any]:
    proposed_waypoints = []
    for marker in markers:
        bias = marker.get("kahn_role_bias")
        if not bias:
            continue
        proposed_waypoints.append(
            {
                "source_role": marker["role"],
                "price": marker["price"],
                "range": marker["range"],
                "candidate_roles": bias,
                "permission": "context_only",
            }
        )

    return {
        "integration_stage": "proposal_only",
        "proposed_waypoint_context": proposed_waypoints,
        "runtime_rule": "Do not feed GexBot levels as Kahn entry/add proof. Convert to campaign waypoints or non-permissive context first.",
    }


def _kahn_role_bias(role: str) -> list[str]:
    if role == "zero_gamma":
        return ["evaluate", "path_stress"]
    if role.startswith("positive_gex") or role == "long_gamma":
        return ["target", "no_add", "evaluate"]
    if role.startswith("negative_gex") or role == "short_gamma":
        return ["target", "no_add", "evaluate"]
    return ["evaluate"]


def _regime_hint(*, sum_gex_oi: float | None, sum_gex_vol: float | None) -> dict[str, Any]:
    value = sum_gex_oi if sum_gex_oi is not None else sum_gex_vol
    if value is None:
        return {"name": "unknown", "basis": None}
    if value > 0:
        return {"name": "positive_gamma", "basis": "sum_gex_oi" if sum_gex_oi is not None else "sum_gex_vol"}
    if value < 0:
        return {"name": "negative_gamma", "basis": "sum_gex_oi" if sum_gex_oi is not None else "sum_gex_vol"}
    return {"name": "neutral", "basis": "sum_gex_oi" if sum_gex_oi is not None else "sum_gex_vol"}


def _zone(price: float, *, tick_size: float, zone_ticks: int) -> dict[str, float]:
    width = max(tick_size, 0.000001) * max(0, zone_ticks)
    return {"lower": price - width, "upper": price + width}


def _timestamp(value: Any) -> str | None:
    number = _number(value)
    if number is None:
        return None
    if number > 10_000_000_000:
        number = number / 1000.0
    return datetime.fromtimestamp(number, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    return number if isfinite(number) else None
