"""Extract EAR DirectConversion retest order attempts for one ET date.

This is a lightweight candidate-list builder for research passes. It keeps the
runtime question narrow: which orders did EAR actually submit because a direct
conversion retest was considered confirmed?
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from _paths import OUTPUT_ROOT


NY = ZoneInfo("America/New_York")
DEFAULT_EVENTS = Path.home() / "Documents" / "ExecAssistantRuntime" / "events.jsonl"
DEFAULT_OUT_DIR = OUTPUT_ROOT


FIELDS = [
    "ts_et",
    "ts_utc",
    "intent_id",
    "directive_id",
    "role",
    "side",
    "quantity",
    "reason",
    "resolution",
    "root_object_id",
    "support_object_id",
    "root_min_price",
    "root_max_price",
    "support_min_price",
    "support_max_price",
    "trigger_bid",
    "trigger_ask",
    "submit_bid",
    "submit_ask",
    "quote_age_ms",
    "root_formed_et",
    "root_age_s",
    "submit_result_accepted",
    "submit_result_order_id",
    "intent_result_accepted",
]


def parse_ts(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def fmt_et(value: str | None) -> str:
    if not value:
        return ""
    return parse_ts(value).astimezone(NY).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def same_et_date(value: str, date: str) -> bool:
    return parse_ts(value).astimezone(NY).date().isoformat() == date


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield line_no, json.loads(line)
            except json.JSONDecodeError:
                continue


def build_rows(path: Path, date: str) -> list[dict[str, object]]:
    rows_by_intent: dict[str, dict[str, object]] = {}
    order: list[str] = []

    for _, event in read_jsonl(path):
        ts_utc = event.get("ts_utc")
        if not ts_utc or not same_et_date(ts_utc, date):
            continue

        name = event.get("event")
        if name == "order_submit":
            if event.get("reason") != "direct_conversion_retest":
                continue
            if event.get("resolution") != "DirectConversion":
                continue
            intent_id = str(event.get("intent_id") or "")
            if not intent_id:
                continue

            root_formed = event.get("root_formed_utc")
            root_age_s = ""
            if root_formed:
                root_age_s = round(
                    (parse_ts(ts_utc) - parse_ts(str(root_formed))).total_seconds(),
                    3,
                )

            row: dict[str, object] = {
                "ts_et": fmt_et(ts_utc),
                "ts_utc": ts_utc,
                "intent_id": intent_id,
                "directive_id": event.get("directive_id", ""),
                "role": event.get("role", ""),
                "side": event.get("side", ""),
                "quantity": event.get("quantity", ""),
                "reason": event.get("reason", ""),
                "resolution": event.get("resolution", ""),
                "root_object_id": event.get("root_object_id", ""),
                "support_object_id": event.get("support_object_id", ""),
                "root_min_price": event.get("root_min_price", ""),
                "root_max_price": event.get("root_max_price", ""),
                "support_min_price": event.get("support_min_price", ""),
                "support_max_price": event.get("support_max_price", ""),
                "trigger_bid": event.get("trigger_bid", ""),
                "trigger_ask": event.get("trigger_ask", ""),
                "submit_bid": event.get("submit_bid", ""),
                "submit_ask": event.get("submit_ask", ""),
                "quote_age_ms": event.get("quote_age_ms", ""),
                "root_formed_et": fmt_et(str(root_formed)) if root_formed else "",
                "root_age_s": root_age_s,
                "submit_result_accepted": "",
                "submit_result_order_id": "",
                "intent_result_accepted": "",
            }
            rows_by_intent[intent_id] = row
            order.append(intent_id)
            continue

        intent_id = str(event.get("intent_id") or "")
        if not intent_id or intent_id not in rows_by_intent:
            continue

        row = rows_by_intent[intent_id]
        if name == "order_submit_result":
            row["submit_result_accepted"] = event.get("accepted", "")
            row["submit_result_order_id"] = event.get("order_id", "")
        elif name == "intent_result":
            row["intent_result_accepted"] = event.get("accepted", "")

    return [rows_by_intent[intent_id] for intent_id in order]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="ET date, YYYY-MM-DD")
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    rows = build_rows(args.events, args.date)
    out = args.out or (DEFAULT_OUT_DIR / f"direct_conversion_retests_{args.date}.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"wrote {out} rows={len(rows)}")


if __name__ == "__main__":
    main()
