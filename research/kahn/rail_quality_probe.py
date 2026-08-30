"""Claude-authored exploratory research artifact.

Do LevelLedger rails re-measure themselves, and can MBO make them do so?

Observation that motivates this. Band 46 on ESU6 2026-08-28 (supply
7775.75-7781.75, formed 11:08:47) emitted:

  11:15:42 TEST @7774.75   11:15:58 HOLD @7773.00
  11:16:17 TEST @7774.75   11:17:08 HOLD @7773.25
  11:18:02 TEST @7774.75   11:18:20 HOLD @7773.00
  11:20:12 TEST @7774.75   11:21:38 HOLD @7772.50
  11:23:13 TEST @7774.75

TEST fires at exactly 7774.75 every time -- the band edge minus the test
buffer. HOLD fires when price backs off. The rail's score stays 76.03 and its
evidence kinds stay frozen at whatever formed it at 11:08:47.

So TEST/HOLD is a price-proximity oscillator over a static band. It carries no
information about whether the liquidity that justified the rail is still there.
Kahn consumes these as `RailTested` / `RailHeld` evidence and can authorise a
probe on them.

This probe asks whether MBO can supply the missing re-measurement: at the
moment a rail is tested, is the side that owns it actually defending?

  consumed      - fill volume on the owning side inside the band (someone is
                  paying to take that liquidity)
  pulled        - unpaid withdrawal on the owning side
  replenish     - adds / removals on the owning side
  paid_share    - consumed / (consumed + pulled)

Label: does the rail subsequently FAIL, or keep holding?
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

import polars as pl

from mbo_level_features import (
    FILL_BUCKET_US, Window, attribute_removals, load_book, load_ticks,
    ny_us, signed_depth_deltas,
)

REPO = Path(__file__).resolve().parents[2]
LL_SCRIPT = REPO / "skills" / "dost" / "scripts" / "ll_bands.py"


def ll_transitions(day: str, symbol_dir: str, window: str,
                   warmup: int = 90, cap: int = 5000) -> list[dict]:
    out = subprocess.run(
        [sys.executable, str(LL_SCRIPT), "--date", day, "--symbol-dir", symbol_dir,
         "--window", window, "--warmup-min", str(warmup),
         "--max-transitions", str(cap), "--format", "json"],
        capture_output=True, text=True, cwd=str(REPO),
    )
    if out.returncode != 0:
        print(f"  ! ll_bands failed {day}: {out.stderr[-300:]}")
        return []
    return json.loads(out.stdout).get("transitions", [])


def hour_flow_table(symbol_dir: str, day: str, hour: int) -> pl.DataFrame:
    """One (t, price, side, fill, pull, add) table per hour.

    Built once and reused for every TEST in that hour -- reloading the book per
    event is what made the first version unusable.
    """
    w = Window(symbol_dir, day, f"{hour:02d}:00", f"{hour + 1:02d}:00")
    book = load_book(w)
    ticks = load_ticks(w)
    rem = (
        attribute_removals(book, ticks)
        .with_columns((pl.col("b") * FILL_BUCKET_US).alias("t"))
        .select("t", "price", "side", "fill_size", "pull_size")
    )
    add = (
        signed_depth_deltas(book)
        .filter(pl.col("size_delta") > 0)
        .select("t", "price", "side", pl.col("size_delta").alias("add_size"))
    )
    return pl.concat([
        rem.with_columns(pl.lit(0.0).alias("add_size")),
        add.with_columns(pl.lit(0.0).alias("fill_size"),
                         pl.lit(0.0).alias("pull_size"))
        .select("t", "price", "side", "fill_size", "pull_size", "add_size"),
    ], how="vertical_relaxed")


def band_flow(tbl: pl.DataFrame, lo: float, hi: float, side: int,
              t0_us: int, t1_us: int) -> dict:
    """Consumed / pulled / added on `side` inside [lo, hi] over a time slice."""
    f = tbl.filter(
        (pl.col("t") > t0_us) & (pl.col("t") <= t1_us) & (pl.col("side") == side)
        & (pl.col("price") >= lo) & (pl.col("price") <= hi)
    )
    if not f.height:
        return {"consumed": 0.0, "pulled": 0.0, "added": 0.0}
    return {"consumed": float(f["fill_size"].sum()),
            "pulled": float(f["pull_size"].sum()),
            "added": float(f["add_size"].sum())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", nargs="+", default=["2026-08-27", "2026-08-28"])
    ap.add_argument("--symbol-dir", default="ESU6")
    ap.add_argument("--window", default="09:45-15:55")
    ap.add_argument("--forward-sec", type=int, default=60,
                    help="feature window AFTER the test, when price actually "
                         "interacts with the band")
    ap.add_argument("--fail-horizon-min", type=float, default=15.0,
                    help="label window, measured from the END of the feature "
                         "window so the label cannot leak into the features")
    a = ap.parse_args()

    rows = []
    for day in a.days:
        tr = ll_transitions(day, a.symbol_dir, a.window)
        print(f"# {day}: {len(tr)} transitions")
        if not tr:
            continue
        # when does each band eventually fail?
        fail_at = {}
        for t in tr:
            if t["action"] == "FAIL" and t["band_id"] not in fail_at:
                fail_at[t["band_id"]] = ny_us(day, t["time"][:5]) + \
                    int(t["time"][6:8]) * 1_000_000
        tests = [t for t in tr if t["action"] == "TEST"]
        cache: dict[int, pl.DataFrame] = {}
        for t in tests:
            hour = int(t["time"][:2])
            if hour not in cache:
                try:
                    cache[hour] = hour_flow_table(a.symbol_dir, day, hour)
                except Exception as exc:
                    print(f"  ! {day} {hour:02d}:00 {type(exc).__name__}")
                    cache[hour] = pl.DataFrame()
            tbl = cache[hour]
            if not tbl.height:
                continue
            t_us = ny_us(day, t["time"][:5]) + int(t["time"][6:8]) * 1_000_000
            side = -1 if t["side"] == "supply" else 1
            feat_end = t_us + a.forward_sec * 1_000_000
            f = band_flow(tbl, t["min_price"], t["max_price"], side,
                          t_us, feat_end)
            ft = fail_at.get(t["band_id"])
            # label strictly AFTER the feature window
            failed_soon = bool(ft and 0 < ft - feat_end <= a.fail_horizon_min * 60e6)
            if ft and ft <= feat_end:
                continue  # already failed inside the feature window
            tot = f["consumed"] + f["pulled"]
            rows.append({
                "day": day, "time": t["time"], "band": t["band_id"],
                "side": t["side"], "score": t["score"],
                "consumed": f["consumed"], "pulled": f["pulled"], "added": f["added"],
                "paid_share": f["consumed"] / tot if tot > 0 else None,
                "replenish": f["added"] / tot if tot > 0 else None,
                "failed_soon": failed_soon,
            })

    df = pl.DataFrame(rows).drop_nulls(["paid_share", "replenish"])
    print(f"\n# TEST events with flow: {df.height}  "
          f"(features {a.forward_sec}s after test, label {a.fail_horizon_min}min after that)")
    if not df.height:
        return

    print(f"\n{'group':>26} {'n':>5} {'paid_share':>11} {'replenish':>10} "
          f"{'consumed':>10} {'pulled':>10} {'LLscore':>8}")
    for label, g in (("rail FAILS within horizon", df.filter(pl.col("failed_soon"))),
                     ("rail holds", df.filter(~pl.col("failed_soon")))):
        if not g.height:
            continue
        print(f"{label:>26} {g.height:5d} {g['paid_share'].median():11.3f} "
              f"{g['replenish'].median():10.3f} {g['consumed'].median():10.0f} "
              f"{g['pulled'].median():10.0f} {g['score'].median():8.2f}")

    # does the CURRENT LevelLedger score separate them? does MBO?
    fail = df.filter(pl.col("failed_soon"))
    hold = df.filter(~pl.col("failed_soon"))
    if fail.height > 5 and hold.height > 5:
        print("\n## separation (Mann-Whitney-style rank AUC, 0.5 = no information)")
        for col in ["score", "paid_share", "replenish", "consumed", "pulled"]:
            fv = fail[col].to_list()
            hv = hold[col].to_list()
            wins = sum(1 for x in fv for y in hv if x > y)
            ties = sum(1 for x in fv for y in hv if x == y)
            auc = (wins + 0.5 * ties) / (len(fv) * len(hv))
            tag = "  <- LevelLedger's own" if col == "score" else ""
            print(f"  {col:>12}: AUC={auc:.3f}  (as failure predictor: "
                  f"{max(auc, 1 - auc):.3f}){tag}")

        # Does the MBO re-measurement add anything ON TOP of the frozen score?
        print("\n## does replenishment add to the frozen score?")
        r = df.select(pl.corr("score", "replenish")).item()
        print(f"  corr(LL score, replenish) = {r:+.3f}")
        smed = df["score"].median()
        rmed = df["replenish"].median()
        print(f"\n  failure rate by quadrant "
              f"(score median {smed:.1f}, replenish median {rmed:.3f})")
        print(f"  {'':>22} {'low replenish':>15} {'high replenish':>15}")
        for slab, scond in (("high LL score", pl.col("score") >= smed),
                            ("low LL score", pl.col("score") < smed)):
            cells = []
            for rcond in (pl.col("replenish") < rmed, pl.col("replenish") >= rmed):
                q = df.filter(scond & rcond)
                cells.append(f"{q['failed_soon'].mean():.1%} (n={q.height})"
                             if q.height else "-")
            print(f"  {slab:>22} {cells[0]:>15} {cells[1]:>15}")


if __name__ == "__main__":
    main()
