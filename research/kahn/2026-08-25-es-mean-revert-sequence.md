# Kahn Mean-Revert Probe Map - ESU6 2026-08-25

Purpose: map the post-open short setup that is different from the true morning
DD/open-reject campaign. This is a responsive/mean-revert family: failed
breakouts above `7690`, edge-only entry/adds, and conservative harvesting into
`7684-7680`.

## Provenance

- MarketRecorder ticks: `ESU6`, `2026-08-25`, `11:40-13:15` ET.
- LevelLedger replay: `ownership_bands_probe.py`, `event_z=2.5`, 180 minute
  warmup.
- BubbleTape rows are fallback grouped tape or delta-mode evidence because
  MarketRecorder identity fields were empty.

## Price Path

| Attempt | Edge Touch | High | Post-Edge Low | Outcome |
|---|---:|---:|---:|---|
| 11:50-12:15 | `12:02:35 >=7690` | `7691.50` | `7686.25` | Did not reach `7684`; scratch/rearm candidate. |
| 12:30-12:50 | `12:30:00 >=7690` | `7692.75` | `7687.00` | Did not reach `7684`; edge failure was not enough. |
| 12:50-13:15 | `12:57:25 >=7690` | `7692.00` | `7682.25` | Reached `7684` at `13:08:34`; did not reach `7680`. |

## BubbleTape Context

- `11:55`: buy groups at `7686.75-7687.00` and `7688.25-7689.00`.
- `12:00`: sell group at `7689.75`, but also buy group at `7690.00-7690.50`.
- `12:25`: heavy two-way edge interaction: sells `7688.50-7689.00` and
  `7690.50-7691.25`, plus buy group `7690.00-7691.50`.
- `12:45`: sell/delta pressure at `7687.00-7687.75`.
- `12:55`: buy groups at `7688.50-7689.00` and `7690.00-7691.00`.
- `13:05`: sell group at `7682.75-7683.75`.

## LevelLedger Read

The first edge attempt had too much live demand below the edge:

- `12:02:36`: demand owned `7686.50-7687.25`.
- `12:03:44`: demand `7683.25-7688.50` formed from supply consumed.
- `12:05:54`: supply owned `7690.25-7691.00`, but price only reached
  `7686.25` after the edge touch.

The second attempt had a better edge, but demand did not fail early enough to
pay:

- `12:31:09`: old upper supply `7692.25-7698.25` tested.
- `12:38:57`: prior `7690.25-7691.00` supply failed as price pushed to
  `7692`.
- `12:43:44`: new supply owned `7691.50-7692.50`.
- `12:44:09`: demand around `7689.25-7691.25` was consumed into supply.
- `12:48:22-12:48:23`: demand `7688.75-7689.00` failed, but price still held
  above the `7684-7680` target.

The later attempt is the cleaner mean-revert expression:

- `12:57-12:59`: tests/holds of `7690.25-7691.75` supply while price revisits
  the edge.
- `13:04:30`: supply owned `7689.00-7691.75`; demand `7689.25-7691.25`
  consumed into supply.
- `13:05:08`: demand `7687.25-7690.00` failed.
- `13:06:23`: demand `7686.50-7687.75` failed.
- `13:08:34`: first target `7684` printed. The final target `7680` did not
  print in this window.

## Kahn Implications

This should not be encoded as the morning DD sell campaign. It needs a
responsive edge-reversion contract:

- `EdgeProbe`: allow initial short only while current executable price is in
  the `7690-7692.50` edge band and there is failed-breakout/supply evidence.
- `EdgePress`: allow adds only on edge retests. Same-side evidence in the
  `7684-7688` body can support holding, but must not worsen average.
- `FieldManage`: monitor demand bands below the edge. Demand failure can keep
  the short alive toward target; demand reload/ownership means scratch, reduce,
  or rearm for a later edge entry.
- `NoProgress`: if an edge entry cannot reach `7684` and demand reloads, exit
  without waiting for a full sponsor failure.
- `TargetHarvest`: `7684` is a pay zone, not a new add zone. Hold for `7680`
  only if demand fails again without reloading.

Current Kahn can approximate this with `trap_probe`, edge-scoped `press`,
`no_add`, `evaluate`, and `target` waypoints, but it lacks one important
primitive: execution-location gating. A rail near the edge is not enough if the
current executable price has already fallen into the body.
