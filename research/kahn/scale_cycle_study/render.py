"""Render recorded price/GEX context and the study's first-add candidates."""
import csv
import json
from collections import Counter
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

import study as s


def dt(t):
    return datetime.fromtimestamp(int(t) / 1e6, s.NY)


def read(name):
    with (s.OUT / name).open(newline="") as f:
        return list(csv.DictReader(f))


def main():
    roots, comparisons = read("roots.csv"), read("first_add_comparison.csv")
    fig, axes = plt.subplots(2, 2, figsize=(18, 12), layout="constrained")
    coverage, summaries = [], []
    styles = {"current_core": ("D", "#246eb2", "Current core"),
              "direct_favorable": ("v", "#ce4d43", "Direct favourable"),
              "warm_joint_range": ("s", "#207a54", "Retained claim + range proof"),
              "warm_joint_price": ("^", "#87549b", "Retained claim + price reclaim")}
    for ax, case in zip(axes.flat, [c for c in s.cases() if c.label == "main"]):
        market = s.Market(case.symbol, case.day)
        start = s.stamp(case.day, "10:50" if case.side == "long" else "09:55")
        end = s.stamp(case.day, "11:20" if case.side == "long" else "11:00")
        quotes = [q for q in market.quotes if start <= q["t"] <= end]
        ax.plot([dt(q["t"]) for q in quotes], [q["mid"] for q in quotes], color="#262d32", lw=.85, label="Captured midpoint")
        for field, color, label in (("zero_gamma", "#bd761b", "Full zero gamma"),
                                    ("call_wall" if case.side == "long" else "put_wall", "#79858a", "Directional wall")):
            points = [(q, market.gamma(q["t"])) for q in quotes]
            ax.plot([dt(q["t"]) for q, g in points],
                    [g.get(field) if g["fresh"] else float("nan") for q, g in points],
                    lw=1.25, color=color, linestyle="--" if field != "zero_gamma" else "-", label=label)
        for root in [r for r in roots if r["case"] == case.name]:
            ax.scatter(dt(root["t"]), float(root["price"]), c="#16191c", marker="o", s=55, zorder=6)
            ax.annotate("Root " + root["root_n"], (dt(root["t"]), float(root["price"])),
                        xytext=(-35, -20 if root["end_reason"] == "root_failure" else 13),
                        textcoords="offset points", fontsize=8)
        notes = []
        for method, (marker, color, label) in styles.items():
            rows = [r for r in comparisons if r["case"] == case.name and r["method"] == method
                    and r["category"] == "gex_full" and r["gate"] == "none" and r["selected"] == "True"]
            for r in rows:
                ax.scatter(dt(r["fill_t"]), float(r["fill_price"]), marker=marker,
                           facecolors="none" if method == "current_core" else color,
                           s=175 if method == "current_core" else 85,
                           edgecolors=color if method == "current_core" else "white",
                           linewidths=1.6 if method == "current_core" else .7,
                           zorder=9 if method == "current_core" else 7, label=label)
                notes.append(f"{label}: {r['time']} / {float(r['fill_price']):.2f}")
            if not rows:
                notes.append(label + ": none")
        ax.set_title(f"{case.symbol} | {case.day} | {case.side.upper()}", loc="left", fontsize=14, weight="bold")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=s.NY))
        ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=5 if case.side == "long" else 10))
        ax.ticklabel_format(axis="y", style="plain", useOffset=False)
        ax.grid(alpha=.15)
        ax.spines[["top", "right"]].set_visible(False)
        ax.text(0, -.17, "\n".join(notes), transform=ax.transAxes, fontsize=9, va="top", linespacing=1.5)
        ax.set_xlabel("New York time", labelpad=6)
        for category in s.CATEGORIES:
            active = [q for q in market.quotes if s.stamp(case.day, case.start) <= q["t"] < s.stamp(case.day, case.end)]
            states = Counter("fresh" if market.gamma(q["t"], category)["fresh"] else "stale" for q in active)
            coverage.append({"case": case.name, "category": category, **states,
                             "stale_percent": round(100 * states["stale"] / len(active), 3)})
    handles, labels = axes.flat[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside upper center", ncol=4, fontsize=10,
               title="Kahn morning scale study | First candidates before gamma vetoes | Hypothetical fills, not historical trades")
    fig.savefig(s.OUT / "morning_scale_comparison.png", dpi=160)
    plt.close(fig)
    for method in s.METHODS:
        for group in ("main", "early-control"):
            rows = [r for r in comparisons if r["case"].endswith(group) and r["method"] == method
                    and r["category"] == "gex_full" and r["gate"] == "none"]
            picked = [r for r in rows if r["selected"] == "True"]
            summaries.append({"group": group, "method": method, "roots": len(rows), "first_candidates": len(picked),
                              "be_not_valid_at_add": sum(r["be_valid_at_add"] == "False" for r in picked),
                              "be_touches_5m": sum(r["be_touch_5m"] == "True" for r in picked),
                              "be_touches_15m": sum(r["be_touch_15m"] == "True" for r in picked)})
    s.write_csv(s.OUT / "gamma_coverage.csv", coverage)
    s.write_csv(s.OUT / "method_summary.csv", summaries)
    print(json.dumps({"chart": str(s.OUT / "morning_scale_comparison.png"), "summary": summaries}, indent=2))


if __name__ == "__main__":
    main()
