"""Render the four shared-episode fixtures and separate inventory experiments."""
from datetime import datetime
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

import episode_study as e
import study as s


def dt(t):
    return datetime.fromtimestamp(t / 1e6, s.NY)


def main():
    fig, axes = plt.subplots(4, 2, figsize=(17, 12), height_ratios=(3, 1.15, 3, 1.15), layout="constrained")
    for index, case in enumerate(c for c in e.cases() if c.label == "main"):
        row, col = (index // 2) * 2, index % 2
        ax, inv = axes[row, col], axes[row + 1, col]
        market = e.Market(case.symbol, case.day)
        lo, hi = s.stamp(case.day, case.start), s.stamp(case.day, case.end)
        root_n = 2 if case.symbol == "NQ" and case.day == "2026-09-03" else 1
        directory = e.OUT / case.name / f"root-{root_n}" / "warm"
        root = json.loads((directory / "root.json").read_text())
        offers = [r for r in s.read_lines(directory / "offers.jsonl") if r["signature"] == "typed_clear"]
        quotes = [q for q in market.quotes if lo <= q["t"] <= hi]
        ax.plot([dt(q["t"]) for q in quotes], [q["mid"] for q in quotes], color="#40474c", lw=.75)
        ax.scatter([dt(r["t"]) for r in offers], [r["price"] for r in offers], marker="o", s=46,
                   facecolors="none", edgecolors="#307da8", lw=1.3, zorder=4, label="Completed typed repair")
        for maximum, management, color, linestyle, label in (
            (2, "tranche_groups", "#727a80", ":", "2 adds; tranche risk"),
            (3, "tranche_groups", "#16825d", "-", "3 adds; tranche risk"),
            (3, "latest_group_campaign", "#c75a30", "--", "3 adds; latest group governs all"),
        ):
            result = json.loads((directory / f"typed_only-{maximum}-{management}.json").read_text())
            inventory = result["inventory"]
            inv.step([dt(lo), dt(root["t"])] + [dt(q["t"]) for q in inventory] + [dt(hi)],
                     [0, 2] + [q["quantity"] for q in inventory] + [result["quantity_before_cutoff"]],
                     where="post", color=color, linestyle=linestyle, lw=1.8, label=label)
            if maximum == 3 and management == "tranche_groups":
                adds = [a for a in result["actions"] if a["action"] == "add"]
                ax.scatter([dt(a["t"]) for a in adds], [a["price"] for a in adds], marker="^", s=57,
                           color=color, zorder=5, label="Delayed add fill proxy")
            if management == "latest_group_campaign":
                exits = [a for a in result["actions"] if a["action"] == "exit" and a["reason"] != "window_mark"]
                ax.scatter([dt(a["t"]) for a in exits], [a["price"] for a in exits], marker="x", s=70,
                           color=color, lw=2, zorder=6)
                for a in exits:
                    ax.annotate("Latest-group exit " + a["time"], (dt(a["t"]), a["price"]),
                                xytext=(-15, 24), textcoords="offset points", ha="right", fontsize=9, color=color)
        ax.scatter(dt(root["t"]), root["price"], color="#161a1d", s=26, zorder=6)
        ax.annotate("Seeded root", (dt(root["t"]), root["price"]), xytext=(8, 12),
                    textcoords="offset points", fontsize=8)
        if root_n == 2:
            failed = json.loads((directory.parents[1] / "root-1/warm/root.json").read_text())
            ax.scatter(dt(failed["t"]), failed["price"], marker="x", color="#bd394b", s=50, zorder=6)
            ax.text(.025, .9, "First root fails 10:56:22", transform=ax.transAxes,
                    fontsize=8, color="#a82d40")
        ax.set_title(f"{case.symbol} | {case.day} | {case.side.upper()} | {case.start}-11:30", loc="left", fontsize=12, weight="bold")
        ax.set_ylabel("Price")
        inv.set_ylabel("Units")
        inv.set_ylim(-.4, 8.5)
        inv.set_yticks((0, 2, 4, 6, 8))
        for panel in (ax, inv):
            panel.set_xlim(dt(lo), dt(hi))
            panel.xaxis.set_major_locator(mdates.MinuteLocator(interval=5 if col == 0 else 15))
            panel.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=s.NY))
            panel.ticklabel_format(axis="y", style="plain", useOffset=False)
            panel.grid(alpha=.14)
            panel.spines[["top", "right"]].set_visible(False)
        ax.legend(loc="lower left" if col else "lower right", fontsize=8)
        inv.legend(loc="lower right", fontsize=7, ncol=1)
        inv.set_xlabel("New York time")
    fig.suptitle("Shared repair episodes | ES and NQ | 2-unit root and tranches\n"
                 "Seeded research, not actual orders. No GEX gates. Risk exits modeled; 11:30 is a mark, not target harvest.", fontsize=13)
    path = e.OUT / "shared_episode_mornings.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    s.write_json(e.OUT / "plot_manifest.json", {
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "study_manifest_sha256": hashlib.sha256((e.OUT / "manifest.json").read_bytes()).hexdigest(),
        "image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    })
    print(path)


if __name__ == "__main__":
    main()
