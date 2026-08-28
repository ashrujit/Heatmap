from __future__ import annotations

import json
from pathlib import Path


OUT = Path("research/kahn/out/2026-08-27-gex-kahn")
SOURCE = Path(r"C:\Users\j\Documents\KahnRuntime\ES\decisions.jsonl")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    campaign = {
        "schema_version": 1,
        "kind": "KAHN_CAMPAIGN",
        "id": "synthetic-es-2026-08-27-long-orr-post-7728",
        "status": "active",
        "created_at": "2026-08-27T13:51:50Z",
        "side": "long",
        "window": {
            "not_before": "2026-08-27T13:51:00Z",
            "expires_at": "2026-08-27T14:20:00Z",
        },
        "arena": {"lower": 7708, "upper": 7744},
        "sizing": {
            "probe_quantity": 2,
            "add_quantity": 2,
            "max_position_quantity": 4,
        },
        "execution": {"max_retry": 3},
        "risk": {
            "root_stop_ticks": 32,
            "sponsor_failure_buffer_ticks": 4,
            "allow_contest_beyond_risk_anchor": True,
        },
        "objective": {
            "target_range": {"lower": 7740, "upper": 7742},
            "target_proximity_ticks": 8,
            "suppress_adds_in_target_zone": True,
        },
        "waypoints": [
            {
                "id": "probe-7716-7726",
                "role": "trap_probe",
                "range": {"lower": 7716, "upper": 7726},
                "require_price_inside": True,
            },
            {
                "id": "no-add-7716-7728",
                "role": "no_add",
                "range": {"lower": 7716, "upper": 7728},
            },
            {
                "id": "press-7728-7732",
                "role": "press",
                "range": {"lower": 7728, "upper": 7732},
                "require_price_inside": True,
                "preserve_risk_anchor_on_add": True,
            },
            {
                "id": "build-7728-7736",
                "role": "build_trial",
                "range": {"lower": 7728, "upper": 7736},
            },
            {
                "id": "harvest-7732-7736",
                "role": "path_stress",
                "range": {"lower": 7732, "upper": 7736},
                "max_position_quantity": 2,
            },
            {
                "id": "target-7741",
                "role": "target",
                "range": {"lower": 7740, "upper": 7742},
            },
            {
                "id": "wrong-below-7712",
                "role": "invalidation",
                "range": {"lower": 7708, "upper": 7712},
            },
        ],
        "notes": (
            "Synthetic reconstruction from ES 2026-08-27 ORR notes: "
            "probe 7716-7726, scale above 7728, harvest 7732-7736, "
            "target 7741. Used to test fixed post-expiry management semantics."
        ),
    }

    (OUT / "synthetic_es_long_original_like.campaign.json").write_text(
        json.dumps(campaign, indent=2) + "\n",
        encoding="utf-8",
    )

    events = [
        {
            "schema_version": 1,
            "event_id": "seed-es-100753-long-probe",
            "ts_utc": "2026-08-27T14:07:53.518048Z",
            "source": "levelledger",
            "kind": "rail_held",
            "side": "demand",
            "price": 7717.5,
            "range": {"lower": 7712.0, "upper": 7714.75},
            "waypoint_id": "probe-7716-7726",
            "score": 20.0,
            "note": (
                "Seed actual third ES ORR long probe so later post-expiry "
                "evidence is managed from position."
            ),
        }
    ]

    kind_map = {
        "RailOwned": "rail_owned",
        "RailHeld": "rail_held",
        "RailFailed": "rail_failed",
        "RailTested": "rail_tested",
    }
    for line in SOURCE.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        timestamp = row.get("ts_utc", "")
        if not ("2026-08-27T14:36:48" <= timestamp[:19] <= "2026-08-27T15:35:59"):
            continue
        if row.get("event") != "ll_transition":
            continue
        if row.get("band_role") != "Rail":
            continue
        kind = kind_map.get(row.get("kind"))
        if kind is None:
            continue
        side = (row.get("band_side") or "").lower()
        if side not in {"demand", "supply"}:
            continue
        events.append(
            {
                "schema_version": 1,
                "event_id": (
                    f"live-ll-{row.get('band_id')}-{row.get('kind')}-"
                    f"{timestamp}"
                ),
                "ts_utc": timestamp,
                "source": "levelledger",
                "kind": kind,
                "side": side,
                "price": row["mid_tick"] * 0.25,
                "range": {
                    "lower": row["band_min_tick"] * 0.25,
                    "upper": row["band_max_tick"] * 0.25,
                },
                "score": row.get("band_score"),
                "note": f"{row.get('kind')} {side} from raw ll_transition",
            }
        )

    (OUT / "synthetic_es_long_post_7728.evidence.jsonl").write_text(
        "\n".join(json.dumps(event, separators=(",", ":")) for event in events)
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(events)} events")


if __name__ == "__main__":
    main()
