# MarketRecorder - Chunked Capture Indicator

## Intent

`MarketRecorder` replaces `L2_Heatmap` as the data-capture surface. It does not
paint a heatmap. Its job is to keep L2 snapshots and trade ticks available for
offline research while making capture health visible during the session.

## Design Decisions

- Capture output is chunked Parquet, not daily append Parquet. The 2026-05-22
  heatmap snapshot file showed why: one bad append/footer can make an entire day
  unreadable. A bad chunk should cost minutes, not the session.
- Files are written to a temporary path, reopened for validation, then renamed
  into place. A chunk is not listed in the manifest until that validation passes.
- A `status.json` file is updated continuously so research tools and manual
  inspection can tell whether ticks, snapshots, and book heartbeat are alive.
- A small chart panel is intentional. A recorder that fails silently is worse
  than no recorder because it creates false confidence in the next-day replay.
- Default snapshot depth is 30 levels per side. Current research scripts use
  `BROAD_LEVELS = 30`; recording 200 levels was inherited from the heatmap and
  costs CPU/disk without current research value. Depth remains configurable.

## Output Shape

```text
captures/<SYMBOL>/
  status.json
  <YYYY-MM-DD>/
    manifest.jsonl
    ticks/
      ticks-HHMMSS-HHMMSS.parquet
    snapshots/
      snapshots-HHMMSS-HHMMSS.parquet
```

The date directory is New York local calendar date, matching how the trader
reviews sessions. Research loaders should scan the datetime window and include
all day directories touched by that window.

## Operational Invariants

- `NewLast` only enqueues ticks. Disk IO happens on the writer task.
- Tick and snapshot producer queues are bounded. If the writer falls behind,
  the recorder drops new rows and exposes monotone drop counters in
  `status.json` and the panel instead of allowing unbounded memory growth.
- L2 callbacks are heartbeat only; snapshots sample `Symbol.DepthOfMarket` on
  the indicator update loop.
- Synthetic Quantower L1-derived pseudo-L2 callbacks
  (`id="generated_from_level1"`, NaN price/size) do not count as a book
  heartbeat. They are not proof that the depth stream is alive.
- Tick and snapshot streams are independent in status and manifest records.
  One can be stale or errored without hiding the other.
- Do not reintroduce append-to-existing Parquet for capture data.
  Append-only is acceptable for `manifest.jsonl` because it is metadata, not the
  research payload.
