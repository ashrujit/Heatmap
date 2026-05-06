"""Walk both trades using two views:
  - level_read: events at a specific price band (for click decisions)
  - show_window: time-ordered events with running bull/bear lean tally
                 (for "what does the sequence say" questions)
"""
import sys
sys.exit_orig = sys.exit
sys.exit = lambda *a, **k: None
exec(open(r"C:/Heatmap/research/liq_events.py", encoding="utf-8").read(), globals())

def show_window(start_hhmm, end_hhmm, label=""):
    """Time-ordered events with running bull/bear lean tally."""
    sub = events_pretty.filter(
        (pl.col("ny") >= start_hhmm) & (pl.col("ny") <= end_hhmm)
    ).sort("ny")
    print(f"\n--- {label} {start_hhmm}-{end_hhmm} ({sub.height} events) ---")
    print(f"  {'time':<10} {'event':<22} {'z':>7} {'price':>9} bias  running")
    bull = 0.0; bear = 0.0
    for r in sub.iter_rows(named=True):
        bias = EVENT_BIAS.get(r["event"], 0)
        bias_s = "+bull" if bias > 0 else ("-bear" if bias < 0 else " neut")
        w = abs(r["z"])
        if bias > 0:   bull += w
        elif bias < 0: bear += w
        net = bull - bear
        arrow = "  " + ("^" * min(5, int(abs(net) / 2))) if net != 0 else "  ."
        if net < 0: arrow = "  " + ("v" * min(5, int(abs(net) / 2)))
        print(f"  {r['ny']:<10} {r['event']:<22} {r['z']:>+7.2f} {r['price']:>9.2f} {bias_s}  "
              f"net {net:+5.1f}{arrow}")
    print(f"  TOTAL: bull={bull:.1f} bear={bear:.1f} net={bull-bear:+.1f}")
    return sub

print("\n" + "=" * 78)
print("WIN TRADE — long off rejection of 28050 floor")
print("=" * 78)

# Sequence read for the trade window
show_window("10:08:00", "10:25:00", "Trade arc")

# Click-decision-grade reads
print("\n--- Click reads (narrow band, short lookback) ---")
level_read(28054, "10:14:30", lookback_min=3, band_ticks=8)
level_read(28050.75, "10:19:30", lookback_min=3, band_ticks=8)

print("\n" + "=" * 78)
print("LOSS TRADE — short 28145 looking for VWAP/VVAL break")
print("=" * 78)

show_window("12:18:00", "12:45:00", "Trade arc — short side")

print("\n--- LONG-watcher question: 12:30-12:40 — did bears already smell weak? ---")
show_window("12:28:00", "12:40:00", "12:28-12:40 from long-watcher view")

print("\n--- LONG-watcher question: 12:40-12:45 — confirmation cluster? ---")
show_window("12:40:00", "12:48:00", "12:40-12:48 confirmation window")

print("\n--- The 'responsive buyers' moment 12:47-12:55 ---")
show_window("12:46:00", "12:55:00", "12:46-12:55 actual reversal")
