# SinglePrints

Standalone Quantower indicator: marks **RTH single-print TPO zones** as horizontal boundary lines (and/or low-alpha box fills) extending to the chart right edge until later trade fills them. Standalone — no shared dependencies with the order-flow suite (no `BookState`, no L2 callbacks, no unsafe code).

## What it shows

For each RTH session (NY 09:30 → 16:00), the indicator finds prices that were traded in **exactly one** bracket of the session (default bracket = 30 min, standard TPO). Contiguous single-print tick prices form zones. Zones extend from their session-end to the chart right edge. Older sessions fade by retention age.

A zone is **dropped** when later trade fully crosses it — i.e., a future session has both `low ≤ zone.bottom` and `high ≥ zone.top`. That's the "gap got closed" / "unfinished business filled" definition. A zone that survives is one nobody has come back to clean up.

No labels, no strength coding, no alerts — same posture as the rest of the suite. A single print is a structural artifact; the trader supplies meaning.

## File map

- `SinglePrints.csproj` — net10.0-windows, AnyCPU. **No nuget deps**, no unsafe code.
- `SinglePrints.cs` — Indicator entry, settings (sortIndex 900-913 in two groups), session-walk + fill logic + render dispatch.
- `SessionBuilder.cs` — pure logic: bars-in-session → bracket-coverage map → contiguous-tick zones. Zero Quantower types, deterministic given inputs.
- `Painter.cs` — converts zones to chart pixels via `IChartWindowCoordinatesConverter`. Single hue, alpha fade by session age.

## Architectural invariants

1. **Bar history, not tape.** Walks `HistoricalData` via inherited `Time(offset)` / `High(offset)` / `Low(offset)`. Wick-counts-as-touched is the standard TPO definition — a 1-tick wick into a price during one bracket marks that price as touched. Simpler data path than tape, deterministic across reloads, no L2 dependency.
2. **Bracket = 30 min default.** Independent of chart bar size as long as bars are ≤ bracket. On larger bars (1h, daily) the output collapses and is meaningless — recommend 1-5 min charts.
3. **Active bracket excluded.** During the in-progress session, only bars from CLOSED brackets feed the computation. Single-print status of the current bracket is by definition undecided. Additionally, the active session is **skipped entirely until ≥2 brackets have closed** — with one bracket of data, every tick has count==1, so the whole range collapses to one degenerate "zone" that carries no information.
4. **Bracket-boundary rebuild trigger.** Rebuild fires on each NY-aligned TPO bracket boundary (09:30, 10:00, 10:30, ...) — NOT on a free-running interval anchored to indicator load. The previous wall-clock gate drifted: a 10:10 load rebuilt at 10:40 instead of 10:30, leaving a closed bracket invisible for up to BracketSizeMin minutes. Outside RTH the boundary key is stable per-day, and a ~30 bar-count delta still triggers rebuilds for historical-data loads (chart symbol change, deep history fill).
5. **Single hue, alpha fade.** Newest session = full alpha; oldest in retention = ~30%. No directional or strength coloring — every zone is "the same kind of thing."
6. **Carry-right-until-filled.** Zones extend from formation time to chart right edge until a later session fully crosses them or they age past the retention window.

## Settings

**Detection** (sortIndex 900-905):
- `Bracket Size (minutes)` — TPO bracket length. 30 standard.
- `Minimum Zone Size (ticks)` — drop zones thinner than this. Default 2; 1-tick singles are mostly fast-wick noise.
- `Sessions to Keep Visible` — retention window in trading days. Default 3.
- `Exclude Session Extremes` — drop zones touching session high/low. **Default OFF.** Buying / selling tails in classic TPO sit *at* session high/low by construction — they are the unretraced edge of an extension and are the most actionable single-print structure, not noise. Verified 2026-05-08 against the live tape: with this ON, both today's selling tail at the open low (28859.50, 856 ticks) and the live buying tail at the high (29248–29316.75, 276 ticks) were silently dropped. Toggle ON only if you specifically want interior singles.

**Render** (sortIndex 910-913):
- `Show Boundary Lines` — horizontal line at zone top + bottom. Default ON.
- `Show Box Fill` — low-alpha rectangle across the zone. Default OFF.
- `Boundary Line Alpha (newest)` / `Box Fill Alpha (newest)` — saturation for the most recent session; older sessions fade.

## Build & deploy

```
dotnet build
```

DLL drops at `C:\Quantower\Settings\Scripts\Indicators\SinglePrints\SinglePrints.dll`. Restart Quantower → right-click chart → Indicators → "Single Prints (RTH TPO)".

## Surfaces deliberately not added

- **No price labels.** The chart's own price scale already labels zones by their Y position.
- **No alerts.** No event semantics — this isn't a signal generator.
- **No "strength" coloring.** Zone thickness or recency-as-color would be classification creep.
- **No tape subscription.** Bar history is sufficient and avoids competing with the order-flow indicators for live data path.
- **No active-bracket provisional render.** The current 30-min bracket's zones aren't single until it closes.

## Zone formation-time semantics

Each zone's `FormedAtUtc` is the **end of the latest bracket among the zone's tick-brackets**, not the latest-closed-bracket of the day. A zone whose ticks were all only touched in bracket A stays anchored to A's close (e.g., NY 10:00) for the rest of the chart's life — so when looking back, the boundary line is drawn through the B / C / D periods where price interacted with the level. This matters because A's single prints are often tested by a B-period IB retrace; the trader needs to see the historical line stretched across that interaction zone, not retroactively snapped to a later bracket boundary.

For mixed-bracket zones (contiguous tickKeys whose individual ticks were single-printed in different brackets), the latest of those brackets wins — the zone isn't fully confirmed until all its component brackets close.

## Known limitations / future calls

- **Bar-resolution sensitivity.** On charts with bars larger than the bracket, output collapses (a 1-hour bar on a 30-min bracket marks all ticks in the bar's range as touched in one bracket). No automatic warning yet — just a doc note.
- **Filling definition is range-spanning, not consolidation-based.** A future session that prints once at the zone bottom and once at the zone top — without dwelling — counts as filled. Stricter "filled = ≥2 brackets traded inside the zone" is conceptually purer but adds state-tracking complexity. Revisit if filled-too-eagerly shows up in live use.
