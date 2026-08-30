"""ES 2026-08-28: mid-relative MBO flow across the short campaign."""
from __future__ import annotations
import argparse, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mbo_level_features import Window, ny_str, coverage_summary
from mbo_flow_series import flow_series

ap = argparse.ArgumentParser()
ap.add_argument("--day", default="2026-08-28")
ap.add_argument("--symbol-dir", default="ESU6")
ap.add_argument("--start", default="11:15")
ap.add_argument("--end", default="12:25")
ap.add_argument("--interval", type=int, default=60)
ap.add_argument("--band-ticks", type=int, default=20)
ap.add_argument("--lo", type=float, default=7700.0)
ap.add_argument("--hi", type=float, default=7800.0)
a = ap.parse_args()

w = Window(a.symbol_dir, a.day, a.start, a.end, price_lo=a.lo, price_hi=a.hi)
cov = coverage_summary(w)
print(f"# {a.symbol_dir} {a.day} {a.start}-{a.end} ET  band {a.lo}-{a.hi}  "
      f"interval={a.interval}s  book_band={a.band_ticks}t from mid")
print(f"# trade_covered={cov['trade_covered']:.3f}  quotes={cov['distinct_quotes']:,}  "
      f"life_med={cov['life_ms_median']:.0f}ms")
print()
print(f"{'time':8} {'close':>8} {'vol':>6} {'delta':>6} | "
      f"{'bidAdd':>7} {'bidFill':>7} {'bidPull':>7} {'bPaid':>6} | "
      f"{'askAdd':>7} {'askFill':>7} {'askPull':>7} {'aPaid':>6} | {'pullImb':>8}")
for r in flow_series(w, a.interval, a.band_ticks).to_dicts():
    print(f"{ny_str(r['bkt']*1_000_000)} {r['close']:8.2f} {r['vol']:6.0f} {r['delta']:+6.0f} | "
          f"{r['bid_add']:7.0f} {r['bid_fill']:7.0f} {r['bid_pull']:7.0f} "
          f"{(r['bid_paid_share'] or 0):6.3f} | "
          f"{r['ask_add']:7.0f} {r['ask_fill']:7.0f} {r['ask_pull']:7.0f} "
          f"{(r['ask_paid_share'] or 0):6.3f} | {r['pull_imbalance']:+8.0f}")
