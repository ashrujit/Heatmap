# Snapshot OFI Proxy — Exploratory Gate

## Question

Can the existing one-second MarketRecorder snapshots show enough positive
pressure-conditioned separation to justify collecting faithful event-level L2
data for OFI research?

This is a gating exercise, not an OFI validation. Periodic snapshots discard
intermediate additions, cancellations, and executions. A negative result could
not reject event-level OFI; a positive result can justify the cost of improving
capture.

## Population

- NQU6, 2026-06-19 09:30-12:55 New York.
- NQU6, 2026-06-22 09:30-16:00 New York.
- Existing LL grammar replayed at its current one-second cadence.
- 521 clean resolved displacement episodes after gap exclusion.
- 173 eventually confirmed; 348 reset.
- June 22 EAR order submissions were retained as descriptive anchors only and
  were not used as the statistical population.

The proxy applies the Cont-style best-bid/best-ask contribution formula between
successive canonical snapshots, normalized by contemporaneous top-book depth.
All scores are oriented toward the episode's eventual demand/supply resolution.
Queue imbalance, aggressor-tape imbalance, and price progress are controls.

## Results

At displacement onset the snapshot OFI proxy was weak:

- 3-second proxy AUC: `0.538`.
- 5-second proxy AUC: `0.495`.

After three seconds of persistence:

- 3-second proxy AUC: `0.621`.
- 5-second proxy AUC: `0.619`.
- Both session-level AUCs had the same positive direction.

After five seconds of persistence:

- 3-second proxy AUC: `0.730`; sign-conditioned confirmation-rate lift:
  `30.3` percentage points.
- 5-second proxy AUC: `0.730`; sign-conditioned confirmation-rate lift:
  `31.5` percentage points.
- Session AUCs were `0.700/0.728` and `0.713/0.732` respectively.

Price progress is an important confound. Five-second aligned price progress had
an AUC of `0.753`, slightly stronger than the snapshot OFI proxy. The proxy was
therefore tested only among similar four-tick price-progress buckets and after
removing its pooled linear relation to price:

| Feature at +5 seconds | Conditional AUC | Residual AUC |
|---|---:|---:|
| 3-second snapshot OFI proxy | 0.653 | 0.629 |
| 5-second snapshot OFI proxy | 0.594 | 0.620 |
| 5-second static-price queue-size change | 0.487 | 0.334 |
| 5-second aggressor-tape imbalance | 0.524 | 0.559 |
| 10-second aggressor-tape imbalance | 0.607 | 0.611 |

The static-price size-only ablation showed no useful separation. This is not
evidence that queue changes have no value; one-second snapshots alias most of
the events required to measure them.

The snapshot proxy also showed no useful separation for directional movement
over the 30 seconds after confirmation:

- 3-second proxy AUC: `0.518`.
- 5-second proxy AUC: `0.496`.
- Queue imbalance and tape controls were also near chance.

## Interpretation

There is enough positive evidence to pursue better data. The useful region is
the transition from displacement to confirmation: pressure may help decide
whether five seconds of persistence is sufficient instead of waiting the fixed
ten seconds.

The result does **not** justify:

- changing LL or EAR confirmation rules;
- reducing live sampling to 250 ms;
- treating the snapshot proxy as faithful OFI;
- using OFI as an add/runway or post-confirmation continuation filter.

The strongest naive result was partly explained by price progress, but positive
separation remained after coarse price conditioning. Two sessions are not
enough for validation, and multiple episodes from the same candidate/session
are correlated.

## Data Work Justified By This Gate

1. Keep the current one-second canonical snapshot and tick streams as
   validation checkpoints.
2. Measure live `NewLevel2` callback rate, full-DOM reset rate, queue high-water,
   and callback field semantics without increasing DOM polling.
3. Design a separate bounded `book_events` stream containing local sequence,
   exchange and receipt times, delta/reset marker, quote id, side, tick price,
   size, `Closed`, implied size, priority, and order count.
4. Treat any dropped event as a continuity gap; reject reconstructed OFI until
   the next authoritative reset.
5. Replay captured events and require agreement with periodic canonical DOM
   snapshots before calculating OFI.
6. Re-run the confirmation study with event-level OFI, event-clock horizons,
   clustered-by-session uncertainty, and held-out session validation.
7. Only after confirmation value is established, formulate a separate study
   for add eligibility, remaining runway, and sponsor resiliency.

## Reproduction

The reusable probe is
`LevelLedger/research/snapshot_ofi_proxy_probe.py`. It writes the summary,
episode rows, confirmation rows, and June 22 EAR-anchor rows beneath
`research/out/`.

```powershell
uv run --with polars --with tzdata python `
  .\LevelLedger\research\snapshot_ofi_proxy_probe.py `
  --session 2026-06-19:NQU6:09:30-12:55 `
  --session 2026-06-22:NQU6:09:30-16:00 `
  --ear-events C:\Users\j\Documents\ExecAssistantRuntime\events.jsonl `
  --out-dir C:\Heatmap\research\out
```
