from __future__ import annotations

import argparse
import csv
import math
from datetime import datetime, timezone
from pathlib import Path

METRICS = [
    "held_ratio_5s",
    "reload_ratio_5s",
    "replenishment_5s",
    "same_depth_change_5s",
    "attack_vol_5s",
    "future_30s_ticks",
]


def parse_window(value: str) -> tuple[str, datetime, datetime]:
    label, start, end = value.split("|", 2)
    return label, datetime.fromisoformat(start).astimezone(timezone.utc), datetime.fromisoformat(end).astimezone(timezone.utc)


def number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def quantile(values: list[float], probability: float) -> float | None:
    clean = sorted(v for v in values if math.isfinite(v))
    if not clean:
        return None
    index = max(0, min(len(clean) - 1, math.ceil(probability * len(clean)) - 1))
    return clean[index]


def rate(rows: list[dict[str, object]]) -> tuple[int, int, float | None]:
    resolved = [row for row in rows if row.get("outcome") in {"confirmed", "reset"}]
    if not resolved:
        return 0, 0, None
    confirmed = sum(1 for row in resolved if row.get("outcome") == "confirmed")
    return confirmed, len(resolved), confirmed / len(resolved)


def auc(rows: list[dict[str, object]], metric: str) -> tuple[int, float | None]:
    pairs: list[tuple[float, int]] = []
    for row in rows:
        if row.get("outcome") not in {"confirmed", "reset"}:
            continue
        value = number(row.get(metric))
        if value is not None:
            pairs.append((value, 1 if row.get("outcome") == "confirmed" else 0))
    pos = sum(label for _, label in pairs)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return len(pairs), None
    ordered = sorted(enumerate(pairs), key=lambda item: item[1][0])
    ranks = [0.0] * len(pairs)
    i = 0
    while i < len(ordered):
        j = i + 1
        while j < len(ordered) and ordered[j][1][0] == ordered[i][1][0]:
            j += 1
        average = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[ordered[k][0]] = average
        i = j
    rank_sum = sum(rank for rank, (_, label) in zip(ranks, pairs) if label)
    return len(pairs), (rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)


def fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def fmt_num(value: float | None) -> str:
    return "" if value is None else f"{value:.3f}".rstrip("0").rstrip(".")


def load_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("gap_contaminated") != "False":
                continue
            if row.get("valid_book") != "True":
                continue
            if row.get("invalidated_by_gap") != "False":
                continue
            if row.get("outcome") not in {"confirmed", "reset"}:
                continue
            row["_anchor_utc"] = datetime.fromisoformat(str(row["anchor_ts"])).astimezone(timezone.utc)
            rows.append(row)
    return rows


def summarize_phase(label: str, rows: list[dict[str, object]]) -> list[str]:
    confirmed, total, pct = rate(rows)
    lines = [f"## {label}", "", f"Resolved clean anchors: `{confirmed}/{total}` `{fmt_pct(pct)}`", ""]
    lines.extend([
        "| metric | p25 low confirmed | p75 high confirmed | AUC |",
        "|---|---:|---:|---:|",
    ])
    for metric in METRICS:
        values = [number(row.get(metric)) for row in rows]
        clean_values = [value for value in values if value is not None]
        lo = quantile(clean_values, 0.25)
        hi = quantile(clean_values, 0.75)
        low_rows = [row for row in rows if (number(row.get(metric)) is not None and lo is not None and number(row.get(metric)) <= lo)]
        high_rows = [row for row in rows if (number(row.get(metric)) is not None and hi is not None and number(row.get(metric)) >= hi)]
        lc, ln, lp = rate(low_rows)
        hc, hn, hp = rate(high_rows)
        n_auc, metric_auc = auc(rows, metric)
        lines.append(
            f"| `{metric}` | `{fmt_num(lo)}`: {lc}/{ln} {fmt_pct(lp)} | "
            f"`{fmt_num(hi)}`: {hc}/{hn} {fmt_pct(hp)} | {'' if metric_auc is None else f'{metric_auc:.3f}'} ({n_auc}) |"
        )
    neg = [row for row in rows if (number(row.get("same_depth_change_5s")) or 0.0) < 0.0]
    nonneg = [row for row in rows if number(row.get("same_depth_change_5s")) is not None and number(row.get("same_depth_change_5s")) >= 0.0]
    nc, nn, npct = rate(neg)
    pc, pn, ppct = rate(nonneg)
    lines.extend([
        "",
        f"- `same_depth_change_5s < 0`: `{nc}/{nn}` `{fmt_pct(npct)}`",
        f"- `same_depth_change_5s >= 0`: `{pc}/{pn}` `{fmt_pct(ppct)}`",
        "",
    ])
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--window", action="append", required=True, help="label|ISO_START|ISO_END")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    rows = load_rows(args.csv)
    lines = ["# Phase Contact Response Summary", "", f"Source: `{args.csv}`", ""]
    for raw in args.window:
        label, start, end = parse_window(raw)
        phase_rows = [row for row in rows if start <= row["_anchor_utc"] < end]
        lines.extend(summarize_phase(label, phase_rows))
    text = "\n".join(lines).rstrip() + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="ascii")
        print(f"wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
