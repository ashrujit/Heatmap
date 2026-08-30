"""ES 2026-08-27 long campaign -- HOLDOUT test of the 8/28 method.

Campaign as declared: long after 11:30 ET at 7728, allowed to scale up to 7730,
harvest above 7743.

Nothing is refitted here. The rail grading uses the same replenishment
threshold (1.012) fitted on the pooled 8/27-8/28 TEST sample, and the fill model
is unchanged.

Realised path after 11:30:
  11:39:15  first print <= 7730
  11:44:03  first print <= 7728
  11:44:14  LL demand id24 (score 109.23) and id25 FAIL at 7728
  ~11:46    session low 7722.75
  11:52-53  LL supply id39 / id37 FAIL -- the turn
  12:34:28  first print >= 7743  (target)
  later     high 7755.50
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbo_level_features import Window, ny_str, ny_us  # noqa: E402
from mbo_fill_sim import FillSimulator, RestingOrder, report  # noqa: E402

# Long: better price is LOWER, so size grows as price improves.
ENTRY_RUNGS = [(7730.00, 2), (7729.50, 2), (7729.00, 3),
               (7728.50, 3), (7728.00, 4)]

HARVEST_PLANS = {
    "flat_at_target": [(7743.00, 14)],
    "tight_ladder":   [(7743.00, 4), (7744.00, 4), (7745.00, 3), (7746.00, 3)],
    "wide_ladder":    [(7743.00, 3), (7744.00, 3), (7745.00, 2), (7746.00, 2),
                       (7747.00, 2), (7748.00, 2)],
    "greedy_ladder":  [(7743.00, 2), (7745.00, 2), (7747.00, 2), (7749.00, 2),
                       (7751.00, 2), (7753.00, 2), (7755.00, 2)],
    "kahn_bbo_clip":  [(7743.00, 1), (7743.25, 1), (7743.50, 1)],
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="2026-08-27")
    ap.add_argument("--symbol-dir", default="ESU6")
    ap.add_argument("--place-entry", default="11:35")
    ap.add_argument("--place-harvest", default="12:30")
    ap.add_argument("--tick-value", type=float, default=12.50)
    a = ap.parse_args()

    ew = Window(a.symbol_dir, a.day, "11:30", "12:05", price_lo=7715, price_hi=7740)
    esim = FillSimulator(ew)
    t0 = ny_us(a.day, a.place_entry)
    eres = esim.ladder([RestingOrder(p, 1, q, t0, 28 * 60 * 1_000_000)
                        for p, q in ENTRY_RUNGS])
    qty, avg_long, oq, oa = report(
        eres, f"ENTRY ladder, bids rested {ny_str(t0)}, TTL 28min")
    print(f"\nentry: conservative {qty:.0f} long @ {avg_long:.4f}   "
          f"optimistic {oq:.0f} @ {oa:.4f}")
    if qty:
        print(f"worst excursion: session low 7722.75 = "
              f"{avg_long - 7722.75:.2f} pts against, "
              f"${(avg_long - 7722.75) / 0.25 * a.tick_value * qty:,.0f} open drawdown")

    hw = Window(a.symbol_dir, a.day, "12:25", "14:30", price_lo=7738, price_hi=7760)
    hsim = FillSimulator(hw)
    h0 = ny_us(a.day, a.place_harvest)
    httl = 115 * 60 * 1_000_000
    print("\n" + "=" * 78)
    print(f"HARVEST comparison: sell {qty:.0f} lots, rested {ny_str(h0)}")
    print("=" * 78)
    rows = []
    for name, plan in HARVEST_PLANS.items():
        res = hsim.ladder([RestingOrder(p, -1, q, h0, httl) for p, q in plan])
        cq, ca, _, _ = report(res, f"harvest: {name}")
        rows.append((name, cq, ca))

    print("\n" + "=" * 78)
    print(f"{'plan':>16} {'sold':>6} {'avg_sell':>10} {'pts/lot':>8} {'realised$':>11} "
          f"{'residual':>9}")
    for name, cq, ca in rows:
        pts = ca - avg_long if cq else 0.0
        print(f"{name:>16} {cq:6.0f} {(f'{ca:10.4f}' if cq else f'{chr(45):>10}')} "
              f"{pts:8.2f} {pts / 0.25 * a.tick_value * cq:11,.0f} {qty - cq:9.0f}")


if __name__ == "__main__":
    main()
