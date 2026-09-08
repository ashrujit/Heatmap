"""Plot full NQ mornings and structural inventory, without GEX or price zones."""
from datetime import datetime
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

import campaign_cycles as c
import study as s


def dt(t):
    return datetime.fromtimestamp(t / 1e6, s.NY)


def main():
    fig, axes = plt.subplots(2, 2, figsize=(16, 9), height_ratios=(3, 1.4), layout="constrained")
    styles = (("current", "#226fa6", "Current source", "o"),
              ("cycle_joint_zone", "#168260", "Research cycle observer", "^"))
    for col, (day, side, start, root) in enumerate((("2026-09-03", "LONG", "10:55", 2),
                                                  ("2026-09-04", "SHORT", "10:00", 1))):
        market = s.Market("NQ", day)
        lo, hi = s.stamp(day, start), s.stamp(day, "11:30")
        quotes = [q for q in market.quotes if lo <= q["t"] <= hi]
        ax, inv = axes[:, col]
        ax.plot([dt(q["t"]) for q in quotes], [q["mid"] for q in quotes], color="#353b40", lw=.85)
        directory = c.OUT / f"NQ-{day}-cycles" / f"root-{root}"
        for variant, color, label, marker in styles:
            folder = directory / f"{variant}-cap10"
            cfg = json.loads((folder / "seed.json").read_text())
            rows = s.read_lines(folder / "policy.jsonl")
            adds = [r for r in rows if r["action"] == "AllowAdd" and r["emitted"]]
            by_order = {e["order"]: e for e in market.events}
            ax.scatter([dt(r["t"]) for r in adds], [by_order[r["order"]]["price"] for r in adds],
                       s=85 if variant == "current" else 65, marker=marker,
                       facecolors="none" if variant == "current" else color,
                       edgecolors=color, lw=1.7, zorder=5, label=label + " adds")
            times = [lo, cfg["seed_t"]] + [r["t"] for r in rows] + [hi]
            quantities = [0, 2] + [r["after"]["quantity"] for r in rows] + [rows[-1]["after"]["quantity"]]
            inv.step([dt(t) for t in times], quantities, where="post", color=color, lw=2,
                     linestyle="--" if variant == "current" else "-", label=label)
        ax.scatter(dt(cfg["seed_t"]), cfg["root_price"], c="#181c20", s=40, zorder=6)
        ax.annotate("Seeded root", (dt(cfg["seed_t"]), cfg["root_price"]), xytext=(12, 14),
                    textcoords="offset points", fontsize=9)
        if day == "2026-09-03":
            failed = json.loads((directory.parent / "root-1/current-cap10/seed.json").read_text())
            ax.scatter(dt(failed["seed_t"]), failed["root_price"], c="#c2474f", marker="x", s=65)
            ax.annotate("First root failed 10:56:22", (dt(failed["seed_t"]), failed["root_price"]),
                        xytext=(12, -23), textcoords="offset points", fontsize=9, color="#a0333b")
        ax.set_title(f"NQ | {day} | {side} | {start}-11:30", loc="left", fontsize=14, weight="bold")
        ax.set_ylabel("NQ price")
        inv.set_ylabel("Hypothetical units")
        inv.set_ylim(-.5, 11)
        inv.set_yticks((0, 2, 4, 6, 8, 10))
        inv.set_xlabel("New York time")
        for panel in (ax, inv):
            panel.set_xlim(dt(lo), dt(hi))
            panel.xaxis.set_major_locator(mdates.MinuteLocator(interval=5 if col == 0 else 15))
            panel.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=s.NY))
            panel.ticklabel_format(axis="y", style="plain", useOffset=False)
            panel.grid(alpha=.16)
            panel.spines[["top", "right"]].set_visible(False)
        ax.legend(loc="best", fontsize=9)
        inv.legend(loc="lower right", fontsize=9)
    fig.suptitle("Full-move scale mechanics | 2-unit root and adds, 10-unit cap\n"
                 "Seeded current-source comparison, not historical fills or validated P&L. No GEX or geographic add gates.", fontsize=13)
    path = c.OUT / "nq_campaign_cycles.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(path)


if __name__ == "__main__":
    main()
