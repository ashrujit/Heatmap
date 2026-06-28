"""Fixture-scoped refill-after-sweep probe.

This is Thesis 7 from the Skurry Now Lens research note. It deliberately builds
on the T4 Brick contact output instead of rediscovering bands. Brick asks what
happened at contact; this pass asks whether the aftermath looks like same-side
passive refill after a sweep/stoprun.

The output is descriptive research data only. It does not consume live EAR logs.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / "research"
DEFAULT_BRICK = RESEARCH / "out" / "brick_contact_response_probe_20260623_20260626.csv"
DEFAULT_OUT_DIR = RESEARCH / "out"

DEFENSE_LIFECYCLES = {
    "clean_hold",
    "weak_hold",
    "weak_hold_same_side_continued",
    "fake_failure_same_side_renewal",
}
CONTESTED_DEFENSE_LIFECYCLES = {
    "weak_hold_opposition_renewed",
    "failure_into_balance",
}
FAILURE_LIFECYCLES = {
    "terminal_failure",
    "no_structural_followthrough",
}
DIRECT_CONVERSION_LIFECYCLES = {
    "direct_conversion_with_followthrough",
}
CHURN_CONVERSION_LIFECYCLES = {
    "conversion_no_followthrough",
    "failed_or_churn_conversion",
}
DEFAULT_ANCHOR_CLASSES = {"band_test", "consumed_conversion"}


def as_float(row: dict[str, str], field: str, default: float = 0.0) -> float:
    value = row.get(field, "")
    if value in ("", None):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def as_bool(row: dict[str, str], field: str) -> bool:
    return str(row.get(field, "")).strip().lower() == "true"


def pct(value: int, total: int) -> str:
    if total <= 0:
        return "n/a"
    return f"{100.0 * value / total:.1f}%"


def outcome_group(lifecycle: str) -> str:
    if lifecycle in DIRECT_CONVERSION_LIFECYCLES:
        return "direct_conversion"
    if lifecycle in CHURN_CONVERSION_LIFECYCLES:
        return "conversion_churn"
    if lifecycle in DEFENSE_LIFECYCLES:
        return "owner_defended"
    if lifecycle in CONTESTED_DEFENSE_LIFECYCLES:
        return "contested_or_balance"
    if lifecycle == "no_structural_followthrough":
        return "no_structural_followthrough"
    if lifecycle == "terminal_failure":
        return "terminal_failure"
    return "other"


def clean_book(row: dict[str, str]) -> bool:
    return as_bool(row, "valid_book") and not as_bool(row, "invalidated_by_gap")


def contact_display(row: dict[str, str]) -> float:
    return max(as_float(row, "contact_start"), as_float(row, "owner_start"))


def refill_base_2s(row: dict[str, str]) -> float:
    return max(
        1.0,
        as_float(row, "attack_vol_2s"),
        as_float(row, "contact_remove_2s"),
        as_float(row, "consumed_estimate_2s"),
    )


def qualifies_sweep(row: dict[str, str], args: argparse.Namespace) -> str | None:
    anchor_class = row.get("anchor_class", "")
    start_display = contact_display(row)
    attack = as_float(row, "attack_vol_2s")
    removed = as_float(row, "contact_remove_2s")
    consumed = as_float(row, "consumed_estimate_2s")
    owner_add = as_float(row, "owner_add_2s")

    displayed = start_display >= args.min_initial_display
    contact_trace = attack >= 1.0 or removed >= 1.0 or consumed >= 1.0
    meaningful_contact = (
        attack >= args.min_attack
        or removed >= args.min_remove
        or consumed >= args.min_consumed
    )

    if anchor_class == "consumed_conversion":
        if displayed and meaningful_contact:
            return "consumed_displayed_sweep"
        if owner_add >= args.min_refill and contact_trace:
            return "consumed_thin_refill_after_trace"
        if args.include_consumed_no_visible_contact:
            return "consumed_synthetic_no_visible_sweep"
        return None

    if displayed and meaningful_contact:
        return "displayed_sweep"
    if not displayed and owner_add >= args.min_refill and contact_trace:
        return "thin_refill_after_trace"
    return None


def refill_label(row: dict[str, str], args: argparse.Namespace) -> str:
    start_display = contact_display(row)
    base = refill_base_2s(row)
    owner_add_fast = as_float(row, "owner_add_250ms")
    owner_add_2s = as_float(row, "owner_add_2s")
    survival = as_float(row, "owner_survival_2s", default=math.nan)
    fast_ratio = owner_add_fast / base
    two_sec_ratio = owner_add_2s / base

    if start_display < args.min_initial_display:
        if owner_add_fast >= args.min_refill and fast_ratio >= args.fast_refill_ratio:
            return "thin_fast_refill"
        if owner_add_2s >= args.min_refill and two_sec_ratio >= args.slow_refill_ratio:
            return "thin_delayed_refill"
        if owner_add_2s >= args.min_refill:
            return "thin_small_refill"
        return "no_visible_refill"

    if owner_add_fast >= args.min_refill and fast_ratio >= args.fast_refill_ratio:
        return "fast_refill"
    if owner_add_2s >= args.min_refill and two_sec_ratio >= args.slow_refill_ratio:
        return "delayed_refill"
    if math.isfinite(survival) and survival >= args.survival_no_refill:
        return "survived_no_refill"
    if math.isfinite(survival) and survival <= args.depleted_survival and owner_add_2s < args.min_refill:
        return "depleted_no_refill"
    if owner_add_2s >= args.min_refill:
        return "small_refill"
    return "mixed_no_refill"


def opposite_refill_context(row: dict[str, str], args: argparse.Namespace) -> str:
    owner_add = as_float(row, "owner_add_2s")
    opp_add = as_float(row, "opp_owner_add_2s")
    if owner_add < args.min_refill and opp_add < args.min_refill:
        return "no_material_refill"
    if owner_add >= args.min_refill and opp_add < args.min_refill:
        return "owner_refill_only"
    if opp_add >= args.min_refill and owner_add < args.min_refill:
        return "opposite_refill_only"
    if owner_add >= opp_add * 1.25:
        return "owner_refill_dominates"
    if opp_add >= owner_add * 1.25:
        return "opposite_refill_dominates"
    return "two_sided_refill"


def aftermath_read(row: dict[str, object]) -> str:
    label = str(row["sweep_refill_label"])
    outcome = str(row["outcome_group"])
    refill_like = {
        "fast_refill",
        "delayed_refill",
        "thin_fast_refill",
        "thin_delayed_refill",
        "thin_small_refill",
        "small_refill",
    }
    no_refill_like = {
        "depleted_no_refill",
        "mixed_no_refill",
        "no_visible_refill",
    }
    if label in refill_like and outcome in {"owner_defended", "direct_conversion"}:
        return "refill_supported_defense"
    if label in refill_like and outcome == "contested_or_balance":
        return "refill_but_contested"
    if label in refill_like and outcome in {"terminal_failure", "no_structural_followthrough", "conversion_churn"}:
        return "refill_failed_to_hold"
    if label == "survived_no_refill" and outcome in {"owner_defended", "direct_conversion"}:
        return "display_survived_defense"
    if label == "survived_no_refill" and outcome == "contested_or_balance":
        return "display_survived_contested"
    if label == "survived_no_refill" and outcome in {"terminal_failure", "no_structural_followthrough", "conversion_churn"}:
        return "display_survived_but_failed"
    if label in no_refill_like and outcome in {"terminal_failure", "no_structural_followthrough", "conversion_churn"}:
        return "continuation_or_failed_repair"
    if label in no_refill_like and outcome in {"owner_defended", "direct_conversion"}:
        return "defense_without_visible_refill"
    return "ambiguous_after_sweep"


def load_rows(path: Path, args: argparse.Namespace) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    result: list[dict[str, str]] = []
    anchor_classes = set(args.anchor_class) if args.anchor_class else DEFAULT_ANCHOR_CLASSES
    for row in rows:
        if row.get("anchor_class") not in anchor_classes:
            continue
        if args.fixture_id and row.get("fixture_id") not in args.fixture_id:
            continue
        if args.bucket and row.get("curated_bucket") not in args.bucket:
            continue
        if args.lifecycle_label and row.get("lifecycle_label") not in args.lifecycle_label:
            continue
        result.append(row)
    return result


def enrich_rows(rows: Iterable[dict[str, str]], args: argparse.Namespace) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for row in rows:
        if not clean_book(row):
            continue
        sweep_kind = qualifies_sweep(row, args)
        if sweep_kind is None:
            continue
        base = refill_base_2s(row)
        owner_add_fast = as_float(row, "owner_add_250ms")
        owner_add_2s = as_float(row, "owner_add_2s")
        lifecycle = row.get("lifecycle_label", "")
        enriched: dict[str, object] = dict(row)
        enriched.update(
            {
                "sweep_kind": sweep_kind,
                "sweep_refill_label": refill_label(row, args),
                "outcome_group": outcome_group(lifecycle),
                "refill_base_2s_recalc": base,
                "fast_refill_ratio_recalc": owner_add_fast / base,
                "two_sec_refill_ratio_recalc": owner_add_2s / base,
                "fast_refill_share": owner_add_fast / max(1.0, owner_add_2s),
                "owner_net_refill_2s": owner_add_2s - as_float(row, "opp_owner_add_2s"),
                "opposite_refill_context": opposite_refill_context(row, args),
            }
        )
        enriched["after_sweep_read"] = aftermath_read(enriched)
        out.append(enriched)
    return out


def count_table(rows: list[dict[str, object]], fields: list[str], outcome_field: str) -> list[str]:
    groups: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in fields)
        groups[key][str(row.get(outcome_field, ""))] += 1
    if not groups:
        return ["No rows."]
    outcomes = sorted({outcome for counter in groups.values() for outcome in counter})
    lines = [
        "| " + " | ".join(fields) + " | n | " + " | ".join(outcomes) + " |",
        "| " + " | ".join("---" for _ in fields) + " | ---: | " + " | ".join("---:" for _ in outcomes) + " |",
    ]
    for key in sorted(groups):
        counter = groups[key]
        total = sum(counter.values())
        cells = [f"{counter[outcome]} ({pct(counter[outcome], total)})" for outcome in outcomes]
        lines.append("| " + " | ".join(key) + f" | {total} | " + " | ".join(cells) + " |")
    return lines


def numeric_summary(rows: list[dict[str, object]], field: str) -> str:
    values: list[float] = []
    for row in rows:
        value = row.get(field)
        if value in ("", None):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            values.append(number)
    if not values:
        return "n/a"
    values.sort()
    mid = values[len(values) // 2]
    p75 = values[min(len(values) - 1, math.ceil(len(values) * 0.75) - 1)]
    return f"n={len(values)} median={mid:.2f} p75={p75:.2f}"


def example_rows(rows: list[dict[str, object]], read_label: str, limit: int = 16) -> list[str]:
    subset = [row for row in rows if row.get("after_sweep_read") == read_label]
    lines = [
        f"### {read_label}",
        "",
        "| fixture | time | anchor | sweep/refill | lifecycle | start | attack2s | remove2s | add250 | add2s |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in subset[:limit]:
        lines.append(
            f"| `{row.get('fixture_id')}` | {row.get('anchor_ny')} | "
            f"{row.get('anchor_class')}@{row.get('contacted_price')} | "
            f"`{row.get('sweep_kind')}` / `{row.get('sweep_refill_label')}` | "
            f"`{row.get('lifecycle_label')}` | "
            f"{float(row.get('owner_start') or 0):.0f} | "
            f"{float(row.get('attack_vol_2s') or 0):.0f} | "
            f"{float(row.get('contact_remove_2s') or 0):.0f} | "
            f"{float(row.get('owner_add_250ms') or 0):.0f} | "
            f"{float(row.get('owner_add_2s') or 0):.0f} |"
        )
    if not subset:
        lines.append("| n/a | n/a | n/a | n/a | n/a | 0 | 0 | 0 | 0 | 0 |")
    return lines


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_report(
    path: Path,
    source_rows: list[dict[str, str]],
    sweep_rows: list[dict[str, object]],
    args: argparse.Namespace,
) -> None:
    source_clean = [row for row in source_rows if clean_book(row)]
    lines = [
        "# Refill After Sweep Probe",
        "",
        "Fixture-scoped Thesis 7 pass. Input rows are the T4 Brick contact metrics; this report relabels sweep aftermath and same-side passive refill.",
        "",
        "## Coverage",
        "",
        f"- source rows after filters: `{len(source_rows)}`",
        f"- clean source rows: `{len(source_clean)}`",
        f"- sweep/refill aftermath rows: `{len(sweep_rows)}`",
        f"- brick source: `{args.brick}`",
        "",
        "## After-Sweep Read By Refill Label",
        "",
    ]
    lines.extend(count_table(sweep_rows, ["sweep_refill_label"], "after_sweep_read"))
    lines.extend(["", "## Outcome Group By Refill Label", ""])
    lines.extend(count_table(sweep_rows, ["sweep_refill_label"], "outcome_group"))
    displayed = [row for row in sweep_rows if row.get("sweep_kind") == "displayed_sweep"]
    consumed = [row for row in sweep_rows if str(row.get("anchor_class")) == "consumed_conversion"]
    lines.extend(["", "## Displayed-Sweep Outcome By Refill Label", ""])
    lines.extend(count_table(displayed, ["sweep_refill_label"], "outcome_group"))
    lines.extend(["", "## Consumed-Conversion Outcome By Refill Label", ""])
    lines.extend(count_table(consumed, ["sweep_refill_label"], "outcome_group"))
    lines.extend(["", "## Refill Label By Sweep Kind", ""])
    lines.extend(count_table(sweep_rows, ["sweep_kind"], "sweep_refill_label"))
    lines.extend(["", "## Anchor Class And Lifecycle", ""])
    lines.extend(count_table(sweep_rows, ["anchor_class", "lifecycle_label"], "sweep_refill_label"))
    lines.extend(["", "## Opposite Refill Context", ""])
    lines.extend(count_table(sweep_rows, ["opposite_refill_context"], "after_sweep_read"))
    lines.extend(["", "## Metric Sketch By Refill Label", ""])
    for label in sorted({str(row.get("sweep_refill_label")) for row in sweep_rows}):
        subset = [row for row in sweep_rows if row.get("sweep_refill_label") == label]
        lines.append(f"- `{label}` attack 2s: {numeric_summary(subset, 'attack_vol_2s')}")
        lines.append(f"- `{label}` contact remove 2s: {numeric_summary(subset, 'contact_remove_2s')}")
        lines.append(f"- `{label}` owner add 250ms: {numeric_summary(subset, 'owner_add_250ms')}")
        lines.append(f"- `{label}` owner add 2s: {numeric_summary(subset, 'owner_add_2s')}")
        lines.append(f"- `{label}` owner survival 2s: {numeric_summary(subset, 'owner_survival_2s')}")
    lines.extend(["", "## Example Rows", ""])
    for read_label in [
        "refill_supported_defense",
        "refill_failed_to_hold",
        "display_survived_defense",
        "display_survived_but_failed",
        "continuation_or_failed_repair",
        "defense_without_visible_refill",
    ]:
        lines.extend(example_rows(sweep_rows, read_label))
        lines.append("")
    lines.extend(
        [
            "## Parameters",
            "",
            f"- min_initial_display: `{args.min_initial_display}`",
            f"- min_attack: `{args.min_attack}`",
            f"- min_remove: `{args.min_remove}`",
            f"- min_consumed: `{args.min_consumed}`",
            f"- min_refill: `{args.min_refill}`",
            f"- fast_refill_ratio: `{args.fast_refill_ratio}`",
            f"- slow_refill_ratio: `{args.slow_refill_ratio}`",
            f"- depleted_survival: `{args.depleted_survival}`",
            f"- survival_no_refill: `{args.survival_no_refill}`",
            f"- include_consumed_no_visible_contact: `{args.include_consumed_no_visible_contact}`",
            "",
            "## Guardrails",
            "",
            "- This pass inherits T4's snapshot-mode limitation: add/remove/refill are net displayed-depth changes, not exchange-native order attribution.",
            "- `250ms` is sample-cadence limited in broad MarketRecorder snapshot mode. Treat fast refill as a candidate row selector, not a final timing statistic.",
            "- `consumed_synthetic_no_visible_sweep` rows are included so broad consumed-conversion behavior is visible, but they are weaker evidence than displayed-sweep rows.",
            "- The labels are descriptive research buckets, not rule changes.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brick", default=str(DEFAULT_BRICK))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--tag", default="20260623_20260626")
    parser.add_argument("--fixture-id", action="append", default=[])
    parser.add_argument("--bucket", action="append", default=[])
    parser.add_argument("--anchor-class", action="append", default=[])
    parser.add_argument("--lifecycle-label", action="append", default=[])
    parser.add_argument("--min-initial-display", type=float, default=1.0)
    parser.add_argument("--min-attack", type=float, default=4.0)
    parser.add_argument("--min-remove", type=float, default=4.0)
    parser.add_argument("--min-consumed", type=float, default=2.0)
    parser.add_argument("--min-refill", type=float, default=2.0)
    parser.add_argument("--fast-refill-ratio", type=float, default=0.50)
    parser.add_argument("--slow-refill-ratio", type=float, default=0.50)
    parser.add_argument("--depleted-survival", type=float, default=0.35)
    parser.add_argument("--survival-no-refill", type=float, default=0.75)
    parser.add_argument("--include-consumed-no-visible-contact", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    source_rows = load_rows(Path(args.brick), args)
    sweep_rows = enrich_rows(source_rows, args)
    out_dir = Path(args.output_dir)
    csv_path = out_dir / f"refill_after_sweep_probe_{args.tag}.csv"
    report_path = out_dir / f"refill_after_sweep_probe_{args.tag}.md"
    write_csv(csv_path, sweep_rows)
    write_report(report_path, source_rows, sweep_rows, args)
    print(f"source rows={len(source_rows)} sweep rows={len(sweep_rows)}")
    print(f"wrote {csv_path}")
    print(f"wrote {report_path}")


if __name__ == "__main__":
    main()
