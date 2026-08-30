"""ES 2026-08-28 short campaign: scale-in and harvest, with queue-aware fills.

Campaign (user-declared): short the 7780 region, issued after 11:20 ET,
harvest target 7740, invalidated by extension above 7782.

Realised path for reference:
  11:26:24  session retest high 7781.50 (session high 7782.50 was at 11:01)
  11:34     rolls over, 11:40 breaks 7758
  11:56:40  first print at/below 7740  -- target reached
  12:01     low 7733.75
  12:09     rallies back to 7745.25   -- 5.25 pts ABOVE target
  12:18     7726.25, later 7711.75 at 13:10

The 12:09 rally is the point of the exercise: a harvest ladder that reaches too
far gets carried back through its own target. Any ladder proposal has to be
scored against that, not just against the 12:01 low.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbo_level_features import Window, ny_str, ny_us  # noqa: E402
from mbo_fill_sim import FillSimulator, RestingOrder, report  # noqa: E402

ENTRY_RUNGS = [(7777.00, 2), (7777.50, 2), (7778.00, 2), (7778.50, 2),
               (7779.00, 3), (7779.50, 3), (7780.00, 3), (7780.50, 3),
               (7781.00, 4), (7781.50, 4)]

HARVEST_PLANS = {
    # name: [(price, qty), ...] -- all sized to cover 24
    "flat_at_target": [(7740.00, 24)],
    "tight_ladder":   [(7740.00, 6), (7739.00, 6), (7738.00, 6), (7737.00, 6)],
    "wide_ladder":    [(7740.00, 4), (7739.00, 4), (7738.00, 4),
                       (7737.00, 4), (7736.00, 4), (7735.00, 4)],
    "greedy_ladder":  [(7740.00, 3), (7738.00, 3), (7736.00, 3), (7734.00, 3),
                       (7732.00, 4), (7730.00, 4), (7728.00, 4)],
    # what Kahn does today: one small clip joining the passive BBO
    "kahn_bbo_clip":  [(7740.00, 1), (7739.75, 1), (7739.50, 1)],
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default="2026-08-28")
    ap.add_argument("--symbol-dir", default="ESU6")
    ap.add_argument("--tick-value", type=float, default=12.50,
                    help="ES = $12.50 per 0.25 tick per contract")
    a = ap.parse_args()

    # ---------- entry ----------
    ew = Window(a.symbol_dir, a.day, "11:20", "11:36", price_lo=7770, price_hi=7790)
    esim = FillSimulator(ew)
    t0 = ny_us(a.day, "11:21")
    ttl = 14 * 60 * 1_000_000
    eres = esim.ladder([RestingOrder(p, -1, q, t0, ttl) for p, q in ENTRY_RUNGS])
    qty, avg_short, opt_qty, opt_avg = report(
        eres, f"ENTRY ladder, offers rested {ny_str(t0)}, TTL 14min")
    print(f"\nentry: conservative {qty:.0f} short @ {avg_short:.4f}   "
          f"optimistic {opt_qty:.0f} @ {opt_avg:.4f}")
    print(f"risk to 7782 invalidation: {7782 - avg_short:.2f} pts on {qty:.0f} lots "
          f"= ${(7782 - avg_short) / 0.25 * a.tick_value * qty:,.0f}")

    # ---------- harvest ----------
    hw = Window(a.symbol_dir, a.day, "11:54", "12:25", price_lo=7720, price_hi=7755)
    hsim = FillSimulator(hw)
    h0 = ny_us(a.day, "11:56")
    httl = 24 * 60 * 1_000_000
    print("\n" + "=" * 78)
    print(f"HARVEST comparison: cover {qty:.0f} lots, ladders rested {ny_str(h0)}, "
          f"TTL 24min (through the 12:09 rally to 7745.25)")
    print("=" * 78)

    # Checkpoints that matter: the counter-rally peak, and the later low.
    checks = [("12:01", 7733.75), ("12:09", 7745.25), ("12:18", 7726.25)]
    rows = []
    for name, plan in HARVEST_PLANS.items():
        res = hsim.ladder([RestingOrder(p, 1, q, h0, httl) for p, q in plan])
        cq, ca, oq, oa = report(res, f"harvest: {name}")
        # open inventory at each checkpoint = requested minus what had filled by then
        opens = []
        for label, _px in checks:
            t = ny_us(a.day, label)
            done = sum(r.filled for r in res
                       if r.first_fill_us is not None and r.first_fill_us <= t)
            opens.append(qty - done)
        rows.append((name, cq, ca, opens))

    print("\n" + "=" * 78)
    print(f"{'plan':>16} {'covered':>8} {'avg_cover':>10} {'pts/lot':>8} "
          f"{'realised$':>11} | open lots at " + "  ".join(f"{c[0]}({c[1]})" for c in checks))
    for name, cq, ca, opens in rows:
        pts = avg_short - ca if cq else 0.0
        dollars = pts / 0.25 * a.tick_value * cq if cq else 0.0
        avg_txt = f"{ca:10.4f}" if cq else f"{'-':>10}"
        print(f"{name:>16} {cq:8.0f} {avg_txt} {pts:8.2f} {dollars:11,.0f} | "
              + "  ".join(f"{o:12.0f}" for o in opens))
    print(f"\nbaseline: short avg {avg_short:.4f} on {qty:.0f} lots. "
          f"Residual lots are still open at 12:20 and must be judged against "
          f"the 12:09 print of 7745.25 and the 13:10 low of 7711.75.")


if __name__ == "__main__":
    main()
