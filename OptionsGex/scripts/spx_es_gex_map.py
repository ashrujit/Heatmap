from __future__ import annotations

import argparse
import csv
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = PACKAGE_ROOT / "input" / "spx_quotedata.csv"
DEFAULT_OUT = PACKAGE_ROOT / "out"


@dataclass(frozen=True)
class OptionRow:
    expiration: datetime.date
    dte: int
    strike: float
    call_oi: float
    put_oi: float
    call_iv: float
    put_iv: float
    call_gamma: float
    put_gamma: float
    call_gex: float
    put_gex: float

    @property
    def net_gex(self) -> float:
        return self.call_gex + self.put_gex

    @property
    def abs_gex(self) -> float:
        return abs(self.call_gex) + abs(self.put_gex)


@dataclass
class Cluster:
    spx: float
    call_oi: float = 0.0
    put_oi: float = 0.0
    call_gex: float = 0.0
    put_gex: float = 0.0
    strikes: int = 0

    @property
    def net_gex(self) -> float:
        return self.call_gex + self.put_gex

    @property
    def abs_gex(self) -> float:
        return abs(self.call_gex) + abs(self.put_gex)


def safe_float(value: str) -> float:
    text = str(value).replace(",", "").strip()
    if not text:
        return math.nan
    try:
        return float(text)
    except ValueError:
        return math.nan


def round_to_increment(value: float, increment: float) -> float:
    return math.floor((value / increment) + 0.5) * increment


def parse_cboe_csv(path: Path, spx_override: float | None = None) -> tuple[str, float, datetime.date, list[OptionRow]]:
    raw_lines = path.read_text(encoding="utf-8-sig").splitlines()
    lines = [line for line in raw_lines if line.strip()]
    if len(lines) < 4:
        raise ValueError(f"{path} does not look like a Cboe quotedata.csv file")

    spot_match = re.search(r"Last:\s*([0-9.]+)", lines[0])
    date_match = re.search(r"Date:\s*([^\"]+)", lines[1])
    if not spot_match or not date_match:
        raise ValueError("Could not parse SPX last or Cboe quote timestamp from CSV preamble")

    spx_reference = spx_override if spx_override is not None else float(spot_match.group(1))
    quote_label = date_match.group(1).strip()
    quote_date = datetime.strptime(" ".join(quote_label.split()[:3]), "%B %d, %Y").date()

    reader = csv.reader(lines[2:])
    header = next(reader)
    validate_header(header)

    rows: list[OptionRow] = []
    for record in reader:
        if len(record) < 22:
            continue

        expiration = datetime.strptime(record[0], "%a %b %d %Y").date()
        dte = (expiration - quote_date).days
        strike = safe_float(record[11])
        call_iv = safe_float(record[7])
        put_iv = safe_float(record[18])
        call_gamma = safe_float(record[9])
        put_gamma = safe_float(record[20])
        call_oi = safe_float(record[10])
        put_oi = safe_float(record[21])

        call_gex = gex_at_reference(call_gamma, call_oi, spx_reference, sign=1.0)
        put_gex = gex_at_reference(put_gamma, put_oi, spx_reference, sign=-1.0)
        rows.append(
            OptionRow(
                expiration=expiration,
                dte=dte,
                strike=strike,
                call_oi=call_oi,
                put_oi=put_oi,
                call_iv=call_iv,
                put_iv=put_iv,
                call_gamma=call_gamma,
                put_gamma=put_gamma,
                call_gex=call_gex,
                put_gex=put_gex,
            )
        )

    return quote_label, spx_reference, quote_date, rows


def validate_header(header: list[str]) -> None:
    required = {
        0: "Expiration Date",
        1: "Calls",
        9: "Gamma",
        10: "Open Interest",
        11: "Strike",
        12: "Puts",
        20: "Gamma",
        21: "Open Interest",
    }
    for index, expected in required.items():
        if index >= len(header) or header[index].strip() != expected:
            found = header[index].strip() if index < len(header) else "<missing>"
            raise ValueError(f"Unexpected Cboe header at column {index}: expected {expected!r}, found {found!r}")


def gex_at_reference(gamma: float, oi: float, spot: float, sign: float) -> float:
    if not all(math.isfinite(x) for x in (gamma, oi, spot)):
        return 0.0
    return sign * gamma * oi * 100.0 * spot * spot * 0.01


def norm_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def bs_gamma(spot: float, strike: float, vol: float, years: float) -> float:
    if spot <= 0.0 or strike <= 0.0 or vol <= 0.0 or years <= 0.0:
        return 0.0
    vol_time = vol * math.sqrt(years)
    d1 = (math.log(spot / strike) + 0.5 * vol * vol * years) / vol_time
    return norm_pdf(d1) / (spot * vol_time)


def total_recomputed_gex(rows: list[OptionRow], spot: float) -> float:
    total = 0.0
    for row in rows:
        years = max(row.dte, 0.25) / 365.0
        if row.call_oi > 0.0 and row.call_iv > 0.0:
            total += bs_gamma(spot, row.strike, row.call_iv, years) * row.call_oi * 100.0 * spot * spot * 0.01
        if row.put_oi > 0.0 and row.put_iv > 0.0:
            total -= bs_gamma(spot, row.strike, row.put_iv, years) * row.put_oi * 100.0 * spot * spot * 0.01
    return total


def zero_gamma_candidates(rows: list[OptionRow], spx_reference: float, width: float, step: float) -> list[float]:
    if not rows:
        return []
    low = math.floor((spx_reference - width) / step) * step
    high = math.ceil((spx_reference + width) / step) * step
    points: list[tuple[float, float]] = []
    current = low
    while current <= high + 1e-9:
        points.append((current, total_recomputed_gex(rows, current)))
        current += step

    zeros: list[float] = []
    for (spot_a, gex_a), (spot_b, gex_b) in zip(points, points[1:]):
        if gex_a == 0.0:
            zeros.append(spot_a)
        elif (gex_a < 0.0 < gex_b) or (gex_a > 0.0 > gex_b):
            zeros.append(spot_a + (0.0 - gex_a) * (spot_b - spot_a) / (gex_b - gex_a))
    return zeros


def build_clusters(rows: list[OptionRow], cluster_points: float) -> list[Cluster]:
    clusters: dict[float, Cluster] = {}
    for row in rows:
        center = round_to_increment(row.strike, cluster_points)
        cluster = clusters.setdefault(center, Cluster(spx=center))
        cluster.call_oi += row.call_oi if math.isfinite(row.call_oi) else 0.0
        cluster.put_oi += row.put_oi if math.isfinite(row.put_oi) else 0.0
        cluster.call_gex += row.call_gex
        cluster.put_gex += row.put_gex
        cluster.strikes += 1
    return list(clusters.values())


def select_clusters(
    clusters: list[Cluster],
    spx_reference: float,
    cluster_points: float,
    upper_count: int,
    lower_count: int,
) -> list[Cluster]:
    anchor_spx = round_to_increment(spx_reference, cluster_points)
    anchor = min(clusters, key=lambda item: abs(item.spx - anchor_spx))
    upper = [item for item in clusters if item.spx > anchor.spx]
    lower = [item for item in clusters if item.spx < anchor.spx]

    selected = [anchor]
    selected.extend(sorted(upper, key=lambda item: item.abs_gex, reverse=True)[:upper_count])
    selected.extend(sorted(lower, key=lambda item: item.abs_gex, reverse=True)[:lower_count])
    return sorted({item.spx: item for item in selected}.values(), key=lambda item: item.spx, reverse=True)


def cluster_role(cluster: Cluster, anchor_spx: float) -> str:
    if cluster.spx == anchor_spx:
        return "Main pin / anchor"
    if cluster.spx > anchor_spx:
        return "Upper positive-GEX wall" if cluster.net_gex >= 0.0 else "Upper mixed wall"
    if cluster.net_gex < 0.0:
        return "Lower negative-GEX shelf"
    if abs(cluster.put_gex) >= 0.35 * max(cluster.abs_gex, 1.0):
        return "Lower mixed shelf"
    return "Lower positive-GEX shelf"


def fmt_price(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{value:.0f}"
    return f"{value:.2f}"


def fmt_es(value: float) -> str:
    return f"{value:.2f}"


def fmt_bn(value: float) -> str:
    return f"{value / 1e9:+.2f}bn"


def render_markdown(
    *,
    quote_label: str,
    spx_reference: float,
    basis: float,
    basis_source: str,
    primary_rows: list[OptionRow],
    all_remaining_rows: list[OptionRow],
    selected: list[Cluster],
    zero_primary: float | None,
    zero_all: float | None,
    dte_min: int,
    dte_max: int,
    cluster_points: float,
    es_tick: float,
    generated_at: datetime,
) -> str:
    expirations = ", ".join(sorted({row.expiration.isoformat() for row in primary_rows})) or "none"
    anchor_spx = round_to_increment(spx_reference, cluster_points)
    generated = generated_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    total_net = sum(row.net_gex for row in primary_rows)
    total_abs = sum(row.abs_gex for row in primary_rows)

    lines = [
        "# SPX -> ES Options GEX Map",
        "",
        f"Generated: {generated}",
        f"Cboe quote: {quote_label}",
        f"SPX reference: {spx_reference:.2f}",
        f"ES basis: {basis:+.2f} ({basis_source})",
        f"Primary expiry window: {dte_min}-{dte_max} calendar DTE; expirations: {expirations}",
        f"Primary total GEX: net {fmt_bn(total_net)}, absolute {total_abs / 1e9:.2f}bn",
        "",
        f"Use these as ES zones, roughly +/-2-3 points. ES levels are rounded to {fmt_price(es_tick)}. They are location context, not trade permission.",
        "",
        "| ES zone | Source SPX | Role | Net GEX | Abs GEX |",
        "|---:|---:|---|---:|---:|",
    ]

    table_items: list[tuple[float, str, str, str, str]] = []
    for cluster in selected:
        es_level = round_to_increment(cluster.spx + basis, es_tick)
        table_items.append(
            (
                es_level,
                fmt_es(es_level),
                fmt_price(cluster.spx),
                cluster_role(cluster, anchor_spx),
                f"{fmt_bn(cluster.net_gex)} | {cluster.abs_gex / 1e9:.2f}bn",
            )
        )
    if zero_primary is not None:
        es_zero = round_to_increment(zero_primary + basis, es_tick)
        table_items.append((es_zero, fmt_es(es_zero), fmt_price(zero_primary), f"Zero gamma, {dte_min}-{dte_max} DTE", "n/a | n/a"))

    for _, es_text, spx_text, role, gex_text in sorted(table_items, key=lambda item: item[0], reverse=True):
        net_text, abs_text = gex_text.split("|", 1)
        lines.append(f"| `{es_text}` | `{spx_text}` | {role} | {net_text.strip()} | {abs_text.strip()} |")

    lines.extend(
        [
            "",
            "Context notes:",
            "- Calls are positive GEX and puts are negative GEX in this naive map.",
            "- Zero gamma is recomputed from Cboe IV/OI with Black-Scholes gamma, r=0, q=0.",
            "- Expired same-day options are excluded from the primary map.",
        ]
    )
    if zero_all is not None and all_remaining_rows:
        lines.append(f"- All remaining non-expired expiries zero gamma: SPX `{fmt_price(zero_all)}`, ES `{fmt_es(round_to_increment(zero_all + basis, es_tick))}`.")
    lines.append("")
    return "\n".join(lines)


def nearest_zero(zeros: list[float], reference: float) -> float | None:
    if not zeros:
        return None
    return min(zeros, key=lambda item: abs(item - reference))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a manual SPX option-chain GEX map translated into ES levels.",
    )
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help=f"Cboe quotedata.csv path. Default: {DEFAULT_CSV}")
    parser.add_argument("--es-reference", type=float, help="ES price synchronized with the SPX reference, usually ES RTH close.")
    parser.add_argument("--basis", type=float, help="Direct ES-SPX basis override. Use instead of --es-reference.")
    parser.add_argument("--spx-reference", type=float, help="Override SPX reference instead of using CSV Last.")
    parser.add_argument("--basis-source", default="", help="Short note describing the basis source.")
    parser.add_argument("--dte-min", type=int, default=1, help="Minimum calendar DTE for primary map.")
    parser.add_argument("--dte-max", type=int, default=5, help="Maximum calendar DTE for primary map.")
    parser.add_argument("--cluster-points", type=float, default=25.0, help="SPX strike bucket size for displayed zones.")
    parser.add_argument("--es-tick", type=float, default=0.25, help="ES tick size used to round translated levels.")
    parser.add_argument("--upper-count", type=int, default=4, help="Number of upper clusters to display.")
    parser.add_argument("--lower-count", type=int, default=4, help="Number of lower clusters to display.")
    parser.add_argument("--zero-width", type=float, default=500.0, help="SPX points around reference for zero-gamma scan.")
    parser.add_argument("--zero-step", type=float, default=5.0, help="SPX grid step for zero-gamma scan.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT, help=f"Output directory. Default: {DEFAULT_OUT}")
    parser.add_argument("--stdout-only", action="store_true", help="Print only; do not write timestamped/latest files.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.es_reference is None and args.basis is None:
        raise SystemExit("Provide --es-reference or --basis.")
    if args.es_reference is not None and args.basis is not None:
        raise SystemExit("Use only one of --es-reference or --basis.")

    quote_label, spx_reference, _quote_date, rows = parse_cboe_csv(args.csv, args.spx_reference)
    basis = args.basis if args.basis is not None else args.es_reference - spx_reference
    basis_source = args.basis_source.strip()
    if not basis_source:
        basis_source = "manual override" if args.basis is not None else f"ES reference {args.es_reference:.2f} minus SPX reference"

    primary_rows = [row for row in rows if args.dte_min <= row.dte <= args.dte_max]
    if not primary_rows:
        raise SystemExit(f"No option rows found for DTE window {args.dte_min}-{args.dte_max}.")
    all_remaining_rows = [row for row in rows if row.dte >= 1]

    clusters = build_clusters(primary_rows, args.cluster_points)
    selected = select_clusters(clusters, spx_reference, args.cluster_points, args.upper_count, args.lower_count)
    zero_primary = nearest_zero(zero_gamma_candidates(primary_rows, spx_reference, args.zero_width, args.zero_step), spx_reference)
    zero_all = nearest_zero(zero_gamma_candidates(all_remaining_rows, spx_reference, args.zero_width, args.zero_step), spx_reference)

    generated_at = datetime.now().astimezone()
    markdown = render_markdown(
        quote_label=quote_label,
        spx_reference=spx_reference,
        basis=basis,
        basis_source=basis_source,
        primary_rows=primary_rows,
        all_remaining_rows=all_remaining_rows,
        selected=selected,
        zero_primary=zero_primary,
        zero_all=zero_all,
        dte_min=args.dte_min,
        dte_max=args.dte_max,
        cluster_points=args.cluster_points,
        es_tick=args.es_tick,
        generated_at=generated_at,
    )

    if not args.stdout_only:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = generated_at.strftime("%Y%m%d-%H%M%S")
        dated_path = args.output_dir / f"{stamp}-spx-es-gex.md"
        latest_path = args.output_dir / "latest.md"
        dated_path.write_text(markdown, encoding="utf-8", newline="\n")
        latest_path.write_text(markdown, encoding="utf-8", newline="\n")
        print(f"Wrote {dated_path}")
        print(f"Wrote {latest_path}")

    print(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
