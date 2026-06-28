# Band Lifecycle Fixture Seeds - 2026-06-22 To 2026-06-26

## Purpose

These are user-memory fixture seeds for the band lifecycle / micro-auction research path. They are not verified conclusions. Each episode should be independently replayed from MarketRecorder before it becomes part of the clean fixture corpus.

Research purpose:

- Separate directional initiative from balance/distribution.
- Avoid broad 55/45 aggregate buckets caused by mixing unlike auction states.
- Build test/failure mode labels before considering any EAR/LL rule changes.

## Data Availability

MarketRecorder NQ data:

- `2026-06-22:NQU6`: archived at `W:\U6 Data Archive\NQU6\2026-06-22`, but currently exclude from automated verification until the mapped Google Drive copy is locally available/reliable.
  - ticks: 281 chunks
  - snapshots: 281 chunks
  - book_events: 456 chunks
- `2026-06-23:NQU6` through `2026-06-27:NQU6`: current capture root at `C:\Quantower\Settings\Scripts\Indicators\MarketRecorder\captures\NQU6`

Important provenance rule:

- These fixtures should be verified from MarketRecorder NQ data and synthetic LL/EAR bands only.
- Do not compare them against live EAR logs from the mixed MNQ/NQ period.

## Fixture Schema

For each verified episode, fill:

- session
- window
- memory label
- verified label
- side
- episode type
- key bands / price areas
- micro-auction boundary
- approach notes
- move-away notes
- test/failure mode
- exclude reason, if any

## 2026-06-22

### 09:30-10:00 ET

Memory label: contested.

Expected episode type:

- balance/distribution or contested open.

Verification questions:

- Did both sides form bands that failed or got run over?
- Was there any durable ownership sequence before 10:00?
- Was this an episode to exclude from continuation-rule research?

### 10:00-11:30/11:45 ET

Memory label: directionally owned by sellers.

Expected episode type:

- directional initiative, supply-owned.

Verification questions:

- Did supply form successive same-side ownership bands?
- Did demand tests fail or get destroyed?
- Did move-away behavior from supply tests show controlled continuation?
- Which supply bands were clean initiative anchors?

### Rest Of Day

Memory label: balance/range, likely supply owned, range bound.

Expected episode type:

- balance/distribution with upper-bound supply.

User hypothesis:

- Upper bound of the range was hitting existing / longer-term supply.
- Lower bounds were no-build zones rather than durable demand.

Verification questions:

- Did upper-bound supply survive repeated tests?
- Did lower-bound demand fail to build, or simply fail to persist?
- Did VPOC/distribution build inside the range?

## 2026-06-23

### 09:30-10:00 ET

Memory label: likely no-build directional up move.

Expected episode type:

- directional price movement without durable band construction.

Verification questions:

- Did price move up without forming useful LL/EAR demand bands?
- Were there low-quality/no-build pullbacks that should be excluded from initiative fixture training?

### 10:00-11:30 ET

Memory label: supply started appearing and making claims that held.

Expected episode type:

- directional or semi-directional supply ownership.

Verification questions:

- Which supply bands formed after 10:00?
- Did they hold tests and destroy demand structure?
- Was this a clean supply initiative fixture or a transition into balance?

### After 11:30 ET

Memory label: builds likely failed or lacked ownership lower, causing deeper repair back into balance.

Expected episode type:

- failure into balance / repair.

Verification questions:

- Did lower ownership fail or never form?
- Did the failed supply/demand areas get revisited?
- Did this become a balance/distribution episode before the afternoon resolution?

### Around 880-890, PM

Memory label: DCS around 880-890 held for rest of PM.

Expected episode type:

- demand/consumed support hold, pending verification.

Verification questions:

- Identify the exact NQ price band behind "880-890".
- Did it hold by clean test, weak hold, or tested-not-disproved?
- Did it produce any follow-on ownership, or simply define range support?

### Around 13:30 ET To Close

Memory label: resolved lower again; supply held until close.

Expected episode type:

- directional initiative, supply-owned.

Verification questions:

- Did supply form a clean sponsor chain after 13:30?
- Did the PM support/DCS finally fail or get consumed?
- Was the move lower initiative or liquidation/no-build?

## 2026-06-24

### 09:30-10:55 ET

Memory label: rotational auction; little durable build or contested builds run over.

Expected episode type:

- balance/distribution or contested.

Verification questions:

- Were early bands mostly failing both ways?
- Did any early ownership survive long enough to matter?
- Should this be excluded from continuation fixture training?

### 10:55-11:10 ET

Memory label: supply started owning.

Expected episode type:

- transition into supply initiative.

Verification questions:

- Which supply band became the first credible sponsor?
- Did it form through normal lean, consumed demand, or failure-zone repair?

### 11:10-12:10 ET

Memory label: repair phase.

Expected episode type:

- repair / balance inside broader supply context.

Verification questions:

- Did sponsor failures here represent true failure, fake failure, or balance repair?
- Did same-side supply renew beyond failed areas?
- Were later short seed locations materially worse than renewal areas?

### 12:10 ET To Close

Memory label: supply owned for the rest of day.

Expected episode type:

- directional initiative, supply-owned.

Verification questions:

- Did supply bands form a persistent chain?
- Did tests hold cleanly or by weak hold?
- Did pull/reload across approach ranges support initiative?

## 2026-06-25

### 09:30-10:00 ET

Memory label: no-build liquidation at open.

Expected episode type:

- liquidation/no-build directional move.

Verification questions:

- Did the open drop lack durable ownership bands?
- Did any bands formed during liquidation fail to survive tests?

### 10:00 ET Onward

Memory label: repair; supply tried to control but kept failing; no durable demand survived either; price did not want lower builds.

Expected episode type:

- balance/distribution / repair.

Verification questions:

- Did both sides fail repeatedly?
- Did lower areas show no-build rather than demand ownership?
- Did VPOC/distribution build?

### Around 10:55 ET

Memory label: supply-owned episode lasting 10-15 minutes.

Expected episode type:

- short-lived directional initiative, supply-owned.

Verification questions:

- Was this a clean supply initiative or just a failed range extension?
- What test/failure mode ended it?

### Around 12:15 ET

Memory label: another supply-owned episode lasting 10-15 minutes.

Expected episode type:

- short-lived directional initiative, supply-owned.

Verification questions:

- Did same-side supply form beyond a failed area?
- Was the move away controlled or liquidation-like?

### Around 14:25/14:30-15:45 ET

Memory label: supply owned into close until about 15:45.

Expected episode type:

- directional initiative, supply-owned.

Verification questions:

- Did supply form successive bands?
- Did any sponsor failure fake out before renewal?
- What ended supply ownership around 15:45?

## 2026-06-26

### Morning / Early Midday

Memory label: up moves were not really built; supply tried, but not successive builds.

Expected episode type:

- no-build up movement / contested supply attempts.

Verification questions:

- Did demand fail to build despite upward movement?
- Did supply attempts fail because price moved through them, or because follow-on ownership never appeared?

### 11:45-11:50 ET

Memory label: supply built.

Expected episode type:

- supply sponsor formation.

Verification questions:

- Identify the exact supply band.
- Was it normal supply lean or consumed demand?
- Did approach/move-away metrics show initiative or only range defense?

### 13:05-13:10 ET

Memory label: 11:45/11:50 supply tested and survived.

Expected episode type:

- clean or weak supply hold.

Verification questions:

- Did price touch/pierce and reject?
- Did the local micro-auction show controlled move away?
- Did opposing demand structure get destroyed afterward?

### 13:10-15:00 ET

Memory label: PM directionally owned lower.

Expected episode type:

- directional initiative, supply-owned.

Verification questions:

- Did supply form a sequence of ownership bands after the test?
- Did tests/failures classify as clean holds, fake failures, or terminal failures?
- Did the episode end near 15:00 through balance, demand repair, or simply loss of initiative?

## Verification Plan

1. Load these windows from MarketRecorder.
2. Generate synthetic LL/EAR bands/transitions for each episode.
3. Mark each episode as directional initiative, balance/distribution, no-build liquidation, repair, or contested.
4. Only then test T4/T5 style micro-auction metrics.
5. Keep broad aggregate studies secondary until the fixture labels are stable.
