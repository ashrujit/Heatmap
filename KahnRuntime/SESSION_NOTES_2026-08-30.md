# KahnRuntime Session Notes - 2026-08-30

## Scaling Model

- Directive semantics should stay coarse: `root_only` versus `scale_allowed`.
  Manual add-price selection is intentionally removed from the directive path.
- `scale_allowed` does not mean add on first worse-price evidence. Adds should
  come from evidence that survives repair/counter-attack and then continues in
  the campaign direction.
- The active sponsor should lag new scale evidence. The first add after root
  queues a child anchor while root remains active risk. A later accepted add can
  promote the previous child and queue the newest child.
- Local LVN separation can support a read, but it is not a required rule. The
  rule belongs to repaired continuation and ownership/sponsorship quality.

## Protection Model

- Root/sponsor failure remains policy evidence, not a broker-side root stop.
  Kahn should flatten only when typed evidence such as `SponsorFailed` or a
  same-side `RailFailed` near the active anchor confirms failure.
- Weighted breakeven is an account backstop after scaled inventory exists. It is
  not armed at root/probe-only size.
- Active `REDUCE` cancels the current breakeven order first, refreshes position
  state, submits the reduce, and lets normal maintenance place a fresh BE for
  the remaining scaled inventory.
- Broker rejects during BE cancel/replace or close submission get one
  position-refresh retry. A second reject is `RecoveryActionRequired` and
  requires manual intervention.

## Hardening

- External JSONL evidence must include `ts_utc` or `timestamp` and pass the
  evidence freshness gate. Kahn drains stale/inactive evidence so a backlog
  cannot become current authority after a new campaign loads.
- Partial JSONL lines are skipped until complete instead of poisoning the
  evidence reader.
- Campaign and control file read failures are logged as runtime state, not
  worker crashes.
- Live quantity is no longer clamped down to plan max; an over-plan live
  position is a recovery condition.

## Smoke Test

- ES and NQ profile-local stale `CANCEL` controls from 2026-08-28 were replaced
  with fresh `CANCEL` controls and acknowledged by the runtimes.
- Disposable active short campaigns were dispatched and loaded:
  - ES/MES: arena/probe `7745:7755`, target/passive harvest `7000:7002`,
    `probe_quantity=1`, `max_position_quantity=1`, `max_retry=1`.
  - NQ/MNQ: arena/probe `29490:29510`, target/passive harvest `29000:29005`,
    `probe_quantity=1`, `max_position_quantity=1`, `max_retry=1`.
- Both campaigns loaded as `RootOnly`, stayed flat, emitted no `order_submit`
  or `order_submit_result`, and were canceled back to `Retired`.
- NQ logged one transient `checkpoint_save_error` before the disposable campaign
  load. Later checkpoint writes and final status checks were clean.
