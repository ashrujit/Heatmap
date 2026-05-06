"""Compute and display the running meter (cumulative lean + rate-of-change)
through both trades. Output is text-based 'meter' visualization at each event
so we can see the dynamic the live meter would show.

cumulative lean: running sum of (bull_weight - bear_weight) across all events
rate-of-change : sum of bias × |z| over rolling 60-sec window (current pressure)
"""
import sys
sys.exit_orig = sys.exit
sys.exit = lambda *a, **k: None
exec(open(r"C:/Heatmap/research/liq_events.py", encoding="utf-8").read(), globals())

ROC_WINDOW_SEC = 60

def meter_bar(value, scale=10.0, width=20):
    """ASCII bar centered, growing left for negative, right for positive."""
    half = width // 2
    n = max(-half, min(half, int(value / scale * half)))
    if n >= 0:
        left = " " * half
        right = "#" * n + " " * (half - n)
    else:
        left = " " * (half + n) + "#" * (-n)
        right = " " * half
    return left + "|" + right

def show_meter(start_hhmm, end_hhmm, label="", scale_cum=8.0, scale_roc=3.0):
    sub = events_pretty.filter(
        (pl.col("ny") >= start_hhmm) & (pl.col("ny") <= end_hhmm)
    ).sort("ny")
    print(f"\n--- {label}  {start_hhmm}-{end_hhmm} ({sub.height} events) ---")
    print(f"  {'time':<10} {'event':<22} {'z':>6} {'price':>8}  cum / roc       cum-meter            roc-meter")

    rows = list(sub.iter_rows(named=True))
    times_sec = [_parse_hhmm(r["ny"]) for r in rows]
    weights = []
    for r in rows:
        bias = EVENT_BIAS.get(r["event"], 0)
        weights.append(bias * abs(r["z"]))

    cum = 0.0
    for i, (r, t_sec, w) in enumerate(zip(rows, times_sec, weights)):
        cum += w
        # rate-of-change: sum of weights in last ROC_WINDOW_SEC
        roc = sum(weights[j] for j in range(i + 1) if t_sec - times_sec[j] <= ROC_WINDOW_SEC)
        cum_m = meter_bar(cum, scale_cum, 20)
        roc_m = meter_bar(roc, scale_roc, 20)
        print(f"  {r['ny']:<10} {r['event']:<22} {r['z']:>+6.2f} {r['price']:>8.2f}  "
              f"{cum:>+5.1f}/{roc:>+5.1f}  {cum_m}  {roc_m}")
    return cum

print("=" * 90)
print("WIN TRADE — long off rejection of 28050 floor")
print("Anchor entries (per user narrative): 28032 ~10:13, 28041 ~10:18-19,")
print("                                     then scale-ins 28057/63/67 walking up")
print("=" * 90)
show_meter("10:08:00", "10:25:00", "WIN — full arc", scale_cum=10.0, scale_roc=4.0)

print("\n" + "=" * 90)
print("LOSS TRADE — short 28145, expecting break to VWAP/VVAL")
print("Anchor: short build 12:18-12:22 around 28145; exits ~12:53 at 28117")
print("=" * 90)
show_meter("12:18:00", "12:55:00", "LOSS — full arc", scale_cum=10.0, scale_roc=4.0)
