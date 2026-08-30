"""GEX field around the ES 2026-08-28 11:20 short campaign.

Reads GexBotMcp SQLite directly (MCP server not required). Emits the wall
timeline plus a local gamma field around the campaign corridor.
"""
from __future__ import annotations
import sqlite3, json, datetime as dt, argparse, os
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
DB = os.environ.get("GEXBOT_CACHE_PATH", r"C:\Heatmap\GexBotMcp\out\gexbot.sqlite")


def rows(ticker: str, category: str, day: str, t0: str, t1: str):
    y, m, d = map(int, day.split("-"))
    h0, m0 = map(int, t0.split(":"))
    h1, m1 = map(int, t1.split(":"))
    a = dt.datetime(y, m, d, h0, m0, tzinfo=NY).astimezone(dt.timezone.utc)
    b = dt.datetime(y, m, d, h1, m1, tzinfo=NY).astimezone(dt.timezone.utc)
    con = sqlite3.connect(DB)
    q = """select recorded_at_utc, spot, zero_gamma, call_wall, put_wall,
                  oi_call_wall, oi_put_wall, sum_gex_vol, sum_gex_oi, raw_json
           from snapshots
           where ticker=? and category=? and ok=1
             and recorded_at_utc>=? and recorded_at_utc<?
           order by recorded_at_utc"""
    out = []
    for r in con.execute(q, (ticker, category, a.strftime("%Y-%m-%dT%H:%M:%S"), b.strftime("%Y-%m-%dT%H:%M:%S"))):
        ts = dt.datetime.fromisoformat(r[0].replace("Z", "+00:00")).astimezone(NY)
        out.append(dict(ts=ts, spot=r[1], zg=r[2], cw=r[3], pw=r[4],
                        oicw=r[5], oipw=r[6], gvol=r[7], goi=r[8],
                        strikes=json.loads(r[9])["strikes"] if r[9] else []))
    return out


def local_field(strikes, lo, hi):
    """gex_vol per strike inside [lo,hi], as {strike: gex_vol}."""
    return {s[0]: s[1] for s in strikes if lo <= s[0] <= hi}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="ES_SPX")
    ap.add_argument("--category", default="gex_zero")
    ap.add_argument("--day", default="2026-08-28")
    ap.add_argument("--from", dest="t0", default="10:50")
    ap.add_argument("--to", dest="t1", default="12:30")
    ap.add_argument("--every", type=int, default=5, help="print every Nth snapshot")
    ap.add_argument("--lo", type=float, default=7720.0)
    ap.add_argument("--hi", type=float, default=7800.0)
    a = ap.parse_args()

    rs = rows(a.ticker, a.category, a.day, a.t0, a.t1)
    print(f"# {a.ticker} {a.category} {a.day} {a.t0}-{a.t1} ET  snapshots={len(rs)}")
    print(f"{'time':8} {'spot':>8} {'zero_g':>8} {'call_w':>8} {'put_w':>8} "
          f"{'oi_cw':>8} {'oi_pw':>8} {'sum_gex_vol':>12}")
    for i, r in enumerate(rs):
        if i % a.every: continue
        print(f"{r['ts'].strftime('%H:%M:%S')} {r['spot']:8.2f} {r['zg']:8.2f} {r['cw']:8.2f} "
              f"{r['pw']:8.2f} {r['oicw']:8.2f} {r['oipw']:8.2f} {r['gvol']:12,.0f}")

    if rs:
        print(f"\n# local gex_vol field {a.lo}-{a.hi}, first vs last snapshot")
        f0 = local_field(rs[0]["strikes"], a.lo, a.hi)
        f1 = local_field(rs[-1]["strikes"], a.lo, a.hi)
        print(f"{'strike':>9} {rs[0]['ts'].strftime('%H:%M'):>14} {rs[-1]['ts'].strftime('%H:%M'):>14} {'delta':>14}")
        for k in sorted(set(f0) | set(f1)):
            v0, v1 = f0.get(k, 0.0), f1.get(k, 0.0)
            print(f"{k:9.2f} {v0:14,.0f} {v1:14,.0f} {v1 - v0:+14,.0f}")


if __name__ == "__main__":
    main()
