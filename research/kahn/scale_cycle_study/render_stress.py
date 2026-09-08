"""Price, permissions, and inventory for the frozen NQ stress fixtures."""
from datetime import datetime
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

import stress_episodes as st
import study as s


def dt(t):
    return datetime.fromtimestamp(t / 1e6, s.NY)


def main():
    st.verify_frozen()
    fig, axes = plt.subplots(2, 3, figsize=(19, 8), height_ratios=(3, 1.4), layout="constrained")
    # The short includes the fixed 12:40 extension, with 12:30 explicitly marked.
    for col, case in enumerate((st.CASES[0], st.CASES[1], st.CASES[3])):
        ax, inv = axes[:, col]
        m = st.market(case.day)
        roots = s.root_seeds(case, m)
        root = roots[-1]
        lo, hi = s.stamp(case.day, case.start), s.stamp(case.day, case.end)
        folder = st.OUT / case.name / f"root-{root['root_n']}" / "warm"
        quotes = [q for q in m.quotes if lo <= q["t"] <= hi]
        offers = [r for r in s.read_lines(folder / "offers.jsonl") if r["signature"] == "typed_clear"]
        ax.plot([dt(q["t"]) for q in quotes], [q["mid"] for q in quotes], lw=.85, color="#3f484e")
        for completion, marker, color, label in (
            ("renewed_defense", "o", "#247ca8", "Defended completion"),
            ("clearance_without_defended_member", "s", "#9a7630", "Fresh clearance; not defended"),
            ("clearance_rebuilt_after_breach", "D", "#7e4c9e", "Rebuilt completion"),
        ):
            rows = [r for r in offers if r["completion"] == completion]
            if rows:
                ax.scatter([dt(r["t"]) for r in rows], [r["price"] for r in rows],
                           marker=marker, s=52, facecolors="none", edgecolors=color, lw=1.2, label=label, zorder=4)
        for maximum, management, color, linestyle, label in (
            (2, "tranche_groups", "#7b8288", ":", "2 adds, tranche risk"),
            (3, "tranche_groups", "#18815e", "-", "3 adds, tranche risk"),
            (3, "latest_group_campaign", "#c45332", "--", "3 adds, latest group governs all"),
        ):
            run = json.loads((folder / f"typed_only-{maximum}-{management}.json").read_text())
            points = run["inventory"]
            inv.step([dt(lo), dt(root["t"])] + [dt(q["t"]) for q in points] + [dt(hi)],
                     [0, 2] + [q["quantity"] for q in points] + [run["quantity_before_cutoff"]],
                     where="post", lw=1.8, color=color, linestyle=linestyle, label=label)
            if maximum == 3 and management == "tranche_groups":
                adds = [a for a in run["actions"] if a["action"] == "add"]
                exits = [a for a in run["actions"] if a["action"] == "exit" and a["reason"] != "window_mark"]
                ax.scatter([dt(a["t"]) for a in adds], [a["price"] for a in adds],
                           marker="^", color=color, s=58, label="Delayed add proxy", zorder=5)
                ax.scatter([dt(a["t"]) for a in exits], [a["price"] for a in exits],
                           marker="x", color="#c45332", s=70, lw=2, zorder=6)
        ax.scatter(dt(root["t"]), root["price"], color="#12181c", s=26, zorder=6)
        if len(roots) > 1:
            failed = roots[0]
            ax.scatter(dt(failed["t"]), failed["price"], color="#b6344a", marker="x", s=40)
            ax.text(.03, .9, "First root exits 10:02:21\nFirst add trimmed 10:09:55", transform=ax.transAxes,
                    fontsize=9, color="#a72b3d")
        elif col == 1:
            ax.text(.03, .9, "Three defended adds\nInventory held to cutoff", transform=ax.transAxes, fontsize=9)
        else:
            ax.text(.04, .10, "BE exit 11:58:43\nLater circles are observations, not held adds", transform=ax.transAxes,
                    fontsize=9, color="#b24629")
            for panel in (ax, inv):
                panel.axvline(dt(s.stamp(case.day, "12:30")), lw=1, linestyle=":", color="#6d7377")
        ax.set_title(f"NQ {case.day} | {case.side.upper()}\n{case.start}-{case.end}", loc="left", fontsize=12, weight="bold")
        ax.set_ylabel("NQ price")
        inv.set_ylabel("Hypothetical units")
        inv.set_ylim(-.4, 8.5)
        inv.set_yticks((0, 2, 4, 6, 8))
        ax.legend(loc="lower right" if col < 2 else "upper right", fontsize=8)
        inv.legend(loc="upper left" if col == 2 else "lower right", fontsize=8)
        for panel in (ax, inv):
            panel.set_xlim(dt(lo), dt(hi))
            panel.xaxis.set_major_locator(mdates.MinuteLocator(interval=5 if col < 2 else 10))
            panel.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=s.NY))
            panel.ticklabel_format(axis="y", style="plain", useOffset=False)
            panel.spines[["top", "right"]].set_visible(False)
            panel.grid(alpha=.14)
        inv.set_xlabel("New York time")
    fig.suptitle("Frozen shared-episode stress test | user-selected NQ windows\n"
                 "No retuning or GEX. Seeded entries; delayed fill and BE proxies. Window ends are marks, not target harvest.", fontsize=13)
    path = st.OUT / "nq_stress_mornings.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    s.write_json(st.OUT / "plot_manifest.json", {"script_sha256": st.sha(Path(__file__)),
                 "study_manifest_sha256": st.sha(st.OUT / "manifest.json"), "image_sha256": st.sha(path)})
    print(path)


if __name__ == "__main__":
    main()
