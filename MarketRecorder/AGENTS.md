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
- Raw L2 events are an additive stream, not a replacement for canonical
  snapshots. Event replay supplies additions/cancellations for OFI research;
  periodic `DepthOfMarket` snapshots remain the independent truth used to
  reject corrupt or incomplete replay intervals.
- Rithmic-via-Quantower can omit closure callbacks for a small number of quote
  ids. Replay may remove a resting level only when a newer opposite-side quote
  makes that level mechanically impossible (bid above ask or ask below bid).
  This crossed-level cleanup is deterministic state repair, not observed flow:
  research must count it, expose its rate, and test OFI with repaired-event
  contributions excluded.
- Event capture consumes the existing `NewLevel2` callbacks and never increases
  DOM polling. The callback copies scalar quote fields into a bounded queue;
  chunking, Parquet conversion, validation, and manifests stay on the writer
  task.
- Quote ids are persisted as stable signed 64-bit FNV-1a-style hashes over the
  .NET UTF-16 code units. Replay needs
  identity continuity, not the broker's opaque text, and retaining millions of
  high-cardinality strings would make callback capture materially more
  expensive. Hash collisions are theoretically possible and must be considered
  if reconstruction disagrees with canonical snapshots.

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
    book_events/
      book-events-HHMMSS-HHMMSS.parquet
```

The date directory is New York local calendar date, matching how the trader
reviews sessions. Research loaders should scan the datetime window and include
all day directories touched by that window.

## Operational Invariants

- `NewLast` only enqueues ticks. Disk IO happens on the writer task.
- Tick and snapshot producer queues are bounded. If the writer falls behind,
  the recorder drops new rows and exposes monotone drop counters in
  `status.json` and the panel instead of allowing unbounded memory growth.
- L2 callbacks update the heartbeat and optionally enqueue raw delta/full-reset
  rows. They never read `Symbol.DepthOfMarket`; snapshots still sample the
  canonical book on the indicator update loop.
- Synthetic Quantower L1-derived pseudo-L2 callbacks
  (`id="generated_from_level1"`, NaN price/size) do not count as a book
  heartbeat. They are not proof that the depth stream is alive.
- Tick and snapshot streams are independent in status and manifest records.
  One can be stale or errored without hiding the other.
- The event stream has its own capacity and short chunk duration. Rows currently
  being serialized still count against that capacity, so a slow Parquet write
  cannot silently double the intended memory ceiling.
- Every lost callback range becomes an explicit `Gap` row. Event replay is
  invalid after a gap until a complete `ResetBegin`/`ResetItem`/`ResetEnd`
  epoch arrives. Deltas before the first complete reset are retained for feed
  diagnostics but are not reconstructable evidence.
- Quantower's feed does not necessarily emit a full `DOMQuote` callback on a
  normal subscription. On startup, and only after a continuity gap, the
  indicator uses the published `IMessageBuilder<DOMQuote>` implementation on
  `DepthOfMarket` to copy the canonical raw book (including quote ids) into a
  reset epoch. This is an on-demand seed, not recurring DOM polling.
- `research/validate_book_events.py` must show acceptable agreement with the
  canonical snapshots before any captured day is admitted to OFI research.
- A reset epoch can begin in the prior New York date partition while the
  recorder process continues through midnight. Validators and research loaders
  must carry the latest preceding reset forward; a local-date folder is not an
  independently seeded replay unit.
- Do not reintroduce append-to-existing Parquet for capture data.
  Append-only is acceptable for `manifest.jsonl` because it is metadata, not the
  research payload.
