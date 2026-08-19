from __future__ import annotations

import argparse
import csv
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = PACKAGE_ROOT / "out"
DEFAULT_SPX_CSV = PACKAGE_ROOT / "input" / "spx_quotedata.csv"
DEFAULT_NDX_CSV = PACKAGE_ROOT / "input" / "ndx_quotedata.csv"


@dataclass(frozen=True)
class ProductConfig:
    key: str
    index_symbol: str
    futures_symbol: str
    default_csv: Path
    output_slug: str
    default_cluster_points: float
    default_zero_width: float
    default_zero_step: float


PRODUCTS: dict[str, ProductConfig] = {
    "spx": ProductConfig(
        key="spx",
        index_symbol="SPX",
        futures_symbol="ES",
        default_csv=DEFAULT_SPX_CSV,
        output_slug="spx-es",
        default_cluster_points=25.0,
        default_zero_width=500.0,
        default_zero_step=5.0,
    ),
    "ndx": ProductConfig(
        key="ndx",
        index_symbol="NDX",
        futures_symbol="NQ",
        default_csv=DEFAULT_NDX_CSV,
        output_slug="ndx-nq",
        default_cluster_points=100.0,
        default_zero_width=2500.0,
        default_zero_step=10.0,
    ),
}


@dataclass(frozen=True)
class OptionRow:
    expiration: date
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
    index_level: float
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


@dataclass(frozen=True)
class GeneratedMap:
    config: ProductConfig
    markdown: str


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


def parse_cboe_csv(
    path: Path,
    index_symbol: str,
    index_override: float | None = None,
) -> tuple[str, float, date, list[OptionRow]]:
    raw_lines = path.read_text(encoding="utf-8-sig").splitlines()
    lines = [line for line in raw_lines if line.strip()]
    if len(lines) < 4:
        raise ValueError(f"{path} does not look like a Cboe quotedata.csv file")

    spot_match = re.search(r"Last:\s*([0-9.]+)", lines[0])
    date_match = re.search(r"Date:\s*([^\"]+)", lines[1])
    if not spot_match or not date_match:
        raise ValueError(f"Could not parse {index_symbol} last or Cboe quote timestamp from CSV preamble")

    index_reference = index_override if index_override is not None else float(spot_match.group(1))
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

        call_gex = gex_at_reference(call_gamma, call_oi, index_reference, sign=1.0)
        put_gex = gex_at_reference(put_gamma, put_oi, index_reference, sign=-1.0)
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

    return quote_label, index_reference, quote_date, rows


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


def zero_gamma_candidates(rows: list[OptionRow], index_reference: float, width: float, step: float) -> list[float]:
    if not rows:
        return []
    low = math.floor((index_reference - width) / step) * step
    high = math.ceil((index_reference + width) / step) * step
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
        cluster = clusters.setdefault(center, Cluster(index_level=center))
        cluster.call_oi += row.call_oi if math.isfinite(row.call_oi) else 0.0
        cluster.put_oi += row.put_oi if math.isfinite(row.put_oi) else 0.0
        cluster.call_gex += row.call_gex
        cluster.put_gex += row.put_gex
        cluster.strikes += 1
    return list(clusters.values())


def select_clusters(
    clusters: list[Cluster],
    index_reference: float,
    cluster_points: float,
    upper_count: int,
    lower_count: int,
) -> list[Cluster]:
    anchor_index = round_to_increment(index_reference, cluster_points)
    anchor = min(clusters, key=lambda item: abs(item.index_level - anchor_index))
    upper = [item for item in clusters if item.index_level > anchor.index_level]
    lower = [item for item in clusters if item.index_level < anchor.index_level]

    selected = [anchor]
    selected.extend(sorted(upper, key=lambda item: item.abs_gex, reverse=True)[:upper_count])
    selected.extend(sorted(lower, key=lambda item: item.abs_gex, reverse=True)[:lower_count])
    return sorted({item.index_level: item for item in selected}.values(), key=lambda item: item.index_level, reverse=True)


def cluster_role(cluster: Cluster, anchor_index: float) -> str:
    if cluster.index_level == anchor_index:
        return "Main pin / anchor"
    if cluster.index_level > anchor_index:
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


def fmt_futures(value: float) -> str:
    return f"{value:.2f}"


def fmt_bn(value: float) -> str:
    return f"{value / 1e9:+.2f}bn"


def render_markdown(
    *,
    config: ProductConfig,
    quote_label: str,
    index_reference: float,
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
    futures_tick: float,
    generated_at: datetime,
) -> str:
    expirations = ", ".join(sorted({row.expiration.isoformat() for row in primary_rows})) or "none"
    anchor_index = round_to_increment(index_reference, cluster_points)
    generated = generated_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    total_net = sum(row.net_gex for row in primary_rows)
    total_abs = sum(row.abs_gex for row in primary_rows)

    lines = [
        f"# {config.index_symbol} -> {config.futures_symbol} Options GEX Map",
        "",
        f"Generated: {generated}",
        f"Cboe quote: {quote_label}",
        f"{config.index_symbol} reference: {index_reference:.2f}",
        f"{config.futures_symbol} basis: {basis:+.2f} ({basis_source})",
        f"Primary expiry window: {dte_min}-{dte_max} calendar DTE; expirations: {expirations}",
        f"Primary total GEX: net {fmt_bn(total_net)}, absolute {total_abs / 1e9:.2f}bn",
        "",
        (
            f"Use these as {config.futures_symbol} zones, roughly +/-2-3 points. "
            f"{config.futures_symbol} levels are rounded to {fmt_price(futures_tick)}. "
            "They are location context, not trade permission."
        ),
        "",
        f"| {config.futures_symbol} zone | Source {config.index_symbol} | Role | Net GEX | Abs GEX |",
        "|---:|---:|---|---:|---:|",
    ]

    table_items: list[tuple[float, str, str, str, str]] = []
    for cluster in selected:
        futures_level = round_to_increment(cluster.index_level + basis, futures_tick)
        table_items.append(
            (
                futures_level,
                fmt_futures(futures_level),
                fmt_price(cluster.index_level),
                cluster_role(cluster, anchor_index),
                f"{fmt_bn(cluster.net_gex)} | {cluster.abs_gex / 1e9:.2f}bn",
            )
        )
    if zero_primary is not None:
        futures_zero = round_to_increment(zero_primary + basis, futures_tick)
        table_items.append(
            (
                futures_zero,
                fmt_futures(futures_zero),
                fmt_price(zero_primary),
                f"Zero gamma, {dte_min}-{dte_max} DTE",
                "n/a | n/a",
            )
        )

    for _, futures_text, index_text, role, gex_text in sorted(table_items, key=lambda item: item[0], reverse=True):
        net_text, abs_text = gex_text.split("|", 1)
        lines.append(f"| `{futures_text}` | `{index_text}` | {role} | {net_text.strip()} | {abs_text.strip()} |")

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
        futures_all = round_to_increment(zero_all + basis, futures_tick)
        lines.append(
            (
                "- All remaining non-expired expiries zero gamma: "
                f"{config.index_symbol} `{fmt_price(zero_all)}`, "
                f"{config.futures_symbol} `{fmt_futures(futures_all)}`."
            )
        )
    lines.append("")
    return "\n".join(lines)


def nearest_zero(zeros: list[float], reference: float) -> float | None:
    if not zeros:
        return None
    return min(zeros, key=lambda item: abs(item - reference))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build manual Cboe option-chain GEX maps translated into futures levels.",
    )
    parser.add_argument(
        "--product",
        choices=("spx", "ndx", "both", "available"),
        default="spx",
        help="Product map to build. Default keeps the legacy SPX->ES behavior.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        help="Single-product Cboe quotedata.csv override. Prefer --spx-csv/--ndx-csv for multi-product runs.",
    )
    parser.add_argument("--spx-csv", type=Path, default=DEFAULT_SPX_CSV, help=f"SPX Cboe CSV path. Default: {DEFAULT_SPX_CSV}")
    parser.add_argument("--ndx-csv", type=Path, default=DEFAULT_NDX_CSV, help=f"NDX Cboe CSV path. Default: {DEFAULT_NDX_CSV}")
    parser.add_argument("--es-reference", type=float, help="ES price synchronized with the SPX reference, usually ES RTH close.")
    parser.add_argument("--nq-reference", type=float, help="NQ price synchronized with the NDX reference, usually NQ RTH close.")
    parser.add_argument("--basis", type=float, help="Single-product futures-index basis override. Legacy SPX alias.")
    parser.add_argument("--spx-basis", type=float, help="Direct ES-SPX basis override. Use instead of --es-reference.")
    parser.add_argument("--ndx-basis", type=float, help="Direct NQ-NDX basis override. Use instead of --nq-reference.")
    parser.add_argument("--spx-reference", type=float, help="Override SPX reference instead of using SPX CSV Last.")
    parser.add_argument("--ndx-reference", type=float, help="Override NDX reference instead of using NDX CSV Last.")
    parser.add_argument("--basis-source", default="", help="Single-product note describing the basis source. Legacy SPX alias.")
    parser.add_argument("--spx-basis-source", default="", help="Short note describing the SPX/ES basis source.")
    parser.add_argument("--ndx-basis-source", default="", help="Short note describing the NDX/NQ basis source.")
    parser.add_argument("--dte-min", type=int, default=1, help="Minimum calendar DTE for primary map.")
    parser.add_argument("--dte-max", type=int, default=5, help="Maximum calendar DTE for primary map.")
    parser.add_argument("--cluster-points", type=float, help="Index strike bucket size for displayed zones. Default: 25 SPX, 100 NDX.")
    parser.add_argument("--futures-tick", type=float, help="Futures tick size used to round translated levels. Default: 0.25.")
    parser.add_argument("--es-tick", type=float, help="Legacy alias for --futures-tick.")
    parser.add_argument("--upper-count", type=int, default=4, help="Number of upper clusters to display.")
    parser.add_argument("--lower-count", type=int, default=4, help="Number of lower clusters to display.")
    parser.add_argument("--zero-width", type=float, help="Index points around reference for zero-gamma scan. Default: 500 SPX, 2500 NDX.")
    parser.add_argument("--zero-step", type=float, help="Index grid step for zero-gamma scan. Default: 5 SPX, 10 NDX.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT, help=f"Output directory. Default: {DEFAULT_OUT}")
    parser.add_argument("--stdout-only", action="store_true", help="Print only; do not write timestamped/latest files.")
    return parser.parse_args()


def selected_product_keys(args: argparse.Namespace) -> list[str]:
    if args.product in ("both", "available") and args.csv is not None:
        raise SystemExit(f"--csv is single-product only; use --spx-csv/--ndx-csv with --product {args.product}.")
    if args.product == "both":
        return ["spx", "ndx"]
    if args.product == "available":
        keys = [key for key, config in PRODUCTS.items() if csv_path_for_product(config, args).exists()]
        if not keys:
            raise SystemExit("No default OptionsGex input CSVs found.")
        return keys
    return [args.product]


def csv_path_for_product(config: ProductConfig, args: argparse.Namespace) -> Path:
    if args.csv is not None:
        return args.csv
    if config.key == "spx":
        return args.spx_csv
    if config.key == "ndx":
        return args.ndx_csv
    raise ValueError(f"Unsupported product {config.key}")


def index_reference_for_product(config: ProductConfig, args: argparse.Namespace) -> float | None:
    if config.key == "spx":
        return args.spx_reference
    if config.key == "ndx":
        return args.ndx_reference
    raise ValueError(f"Unsupported product {config.key}")


def basis_inputs_for_product(
    config: ProductConfig,
    args: argparse.Namespace,
    product_count: int,
) -> tuple[float | None, float | None]:
    if args.basis is not None and product_count > 1:
        raise SystemExit("--basis is single-product only; use --spx-basis and/or --ndx-basis for multi-product runs.")

    if config.key == "spx":
        if args.basis is not None and args.spx_basis is not None:
            raise SystemExit("Use only one of --basis or --spx-basis.")
        return args.spx_basis if args.spx_basis is not None else args.basis, args.es_reference
    if config.key == "ndx":
        if args.basis is not None and args.ndx_basis is not None:
            raise SystemExit("Use only one of --basis or --ndx-basis.")
        return args.ndx_basis if args.ndx_basis is not None else args.basis, args.nq_reference
    raise ValueError(f"Unsupported product {config.key}")


def basis_source_for_product(
    config: ProductConfig,
    args: argparse.Namespace,
    basis_override: float | None,
    futures_reference: float | None,
) -> str:
    if config.key == "spx":
        specific = args.spx_basis_source.strip()
    elif config.key == "ndx":
        specific = args.ndx_basis_source.strip()
    else:
        raise ValueError(f"Unsupported product {config.key}")

    if specific:
        return specific

    generic = args.basis_source.strip()
    if generic:
        return generic

    if basis_override is not None:
        return "manual override"
    if futures_reference is None:
        raise ValueError("futures_reference is required without a basis override")
    return f"{config.futures_symbol} reference {futures_reference:.2f} minus {config.index_symbol} reference"


def resolved_futures_tick(args: argparse.Namespace) -> float:
    if args.futures_tick is not None and args.es_tick is not None and args.futures_tick != args.es_tick:
        raise SystemExit("Use only one of --futures-tick or --es-tick.")
    if args.futures_tick is not None:
        return args.futures_tick
    if args.es_tick is not None:
        return args.es_tick
    return 0.25


def build_product_map(
    config: ProductConfig,
    args: argparse.Namespace,
    product_count: int,
    generated_at: datetime,
) -> GeneratedMap:
    csv_path = csv_path_for_product(config, args)
    if not csv_path.exists():
        raise SystemExit(f"{config.index_symbol} input CSV not found: {csv_path}")

    basis_override, futures_reference = basis_inputs_for_product(config, args, product_count)
    if basis_override is None and futures_reference is None:
        raise SystemExit(f"Provide --{config.futures_symbol.lower()}-reference or --{config.key}-basis.")
    if basis_override is not None and futures_reference is not None:
        raise SystemExit(f"Use only one of --{config.futures_symbol.lower()}-reference or --{config.key}-basis.")

    quote_label, index_reference, _quote_date, rows = parse_cboe_csv(
        csv_path,
        config.index_symbol,
        index_reference_for_product(config, args),
    )
    basis = basis_override if basis_override is not None else futures_reference - index_reference
    basis_source = basis_source_for_product(config, args, basis_override, futures_reference)

    primary_rows = [row for row in rows if args.dte_min <= row.dte <= args.dte_max]
    if not primary_rows:
        raise SystemExit(f"No {config.index_symbol} option rows found for DTE window {args.dte_min}-{args.dte_max}.")
    all_remaining_rows = [row for row in rows if row.dte >= 1]

    cluster_points = args.cluster_points if args.cluster_points is not None else config.default_cluster_points
    zero_width = args.zero_width if args.zero_width is not None else config.default_zero_width
    zero_step = args.zero_step if args.zero_step is not None else config.default_zero_step

    clusters = build_clusters(primary_rows, cluster_points)
    selected = select_clusters(clusters, index_reference, cluster_points, args.upper_count, args.lower_count)
    zero_primary = nearest_zero(zero_gamma_candidates(primary_rows, index_reference, zero_width, zero_step), index_reference)
    zero_all = nearest_zero(zero_gamma_candidates(all_remaining_rows, index_reference, zero_width, zero_step), index_reference)

    markdown = render_markdown(
        config=config,
        quote_label=quote_label,
        index_reference=index_reference,
        basis=basis,
        basis_source=basis_source,
        primary_rows=primary_rows,
        all_remaining_rows=all_remaining_rows,
        selected=selected,
        zero_primary=zero_primary,
        zero_all=zero_all,
        dte_min=args.dte_min,
        dte_max=args.dte_max,
        cluster_points=cluster_points,
        futures_tick=resolved_futures_tick(args),
        generated_at=generated_at,
    )
    return GeneratedMap(config=config, markdown=markdown)


def combined_markdown(generated_maps: list[GeneratedMap]) -> str:
    return "\n---\n\n".join(item.markdown.rstrip() for item in generated_maps) + "\n"


def write_outputs(args: argparse.Namespace, generated_maps: list[GeneratedMap], generated_at: datetime) -> None:
    if args.stdout_only:
        return

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.strftime("%Y%m%d-%H%M%S")
    for generated in generated_maps:
        dated_path = args.output_dir / f"{stamp}-{generated.config.output_slug}-gex.md"
        latest_product_path = args.output_dir / f"latest-{generated.config.output_slug}.md"
        dated_path.write_text(generated.markdown, encoding="utf-8", newline="\n")
        latest_product_path.write_text(generated.markdown, encoding="utf-8", newline="\n")
        print(f"Wrote {dated_path}")
        print(f"Wrote {latest_product_path}")

    combined = combined_markdown(generated_maps)
    latest_path = args.output_dir / "latest.md"
    latest_path.write_text(combined, encoding="utf-8", newline="\n")
    print(f"Wrote {latest_path}")

    if len(generated_maps) > 1:
        combined_path = args.output_dir / f"{stamp}-options-gex.md"
        combined_path.write_text(combined, encoding="utf-8", newline="\n")
        print(f"Wrote {combined_path}")


def main() -> int:
    args = parse_args()
    keys = selected_product_keys(args)
    generated_at = datetime.now().astimezone()
    maps = [build_product_map(PRODUCTS[key], args, len(keys), generated_at) for key in keys]

    write_outputs(args, maps, generated_at)
    print(combined_markdown(maps))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
