# Bounded observation catch-up

## Problem and resulting behavior

The old worker read only the current DOM and discarded the rolling discovery
history on a book mismatch or a worker observation gap. A busy order/file worker
could therefore impose another 30-second warmup even while QT kept delivering
usable books. Arrival timestamps also allowed old deliveries to look fresh.

A dedicated background thread now copies a validated top-30 book and matching
BBO at the configured Book Sample interval (1 second by default). Lightweight
price observations retain worker-frequency repair updates (250 ms by default).
Both enter one bounded buffer; the worker consumes them in capture order.
Capture performs no policy decisions, file writes or broker actions.

| Condition | Recovery |
| --- | --- |
| Worker backlog with retained ordered samples | Preserve LL baseline and owners; hydrate historical risk; resume on a fresh observation after catch-up started |
| Brief unusable or torn book within existing maximum sample gap | Retry read up to three times; veto new risk; clear unfinished candidates and failure timers; retain statistical baseline |
| Capture gap beyond existing L2 Freshness limit | Full observation reset and configured warmup |
| Buffer overflow, capture timestamp reversal, or connection change | Full observation reset; preserve existing owner identities and confirmed failures |
| QT delivers delayed data | Source-age checks gate freshness; no claim of reconstructing private QT history |

The defaults remain a 5-second maximum sample gap and a 30-second LL lookback.
No root stop, failure threshold, ownership identity or execution authorization
rule is relaxed. Historical batches cannot supply root-entry or add triggers.
Catch-up invalidates unfilled scale proof; filled owners remain monitored through
complete retained LL snapshots. Missing time cannot count toward failure timers.

## Timing and adapter constraints

The capture thread is independent of the trading worker and .NET ThreadPool, but
can still be delayed by process-wide pauses, CPU starvation or QT DOM reads.
A DOM read taking longer than the book sample interval is rejected instead of
stamping a late result with its earlier start time. Capture cannot recover samples that were never captured. Each callback retains source
time and local arrival time separately. Missing/regressed source timestamps fail
closed; timestamps more than 250 ms ahead of local UTC are rejected without
poisoning the source high-water mark. Equal source times remain valid. Provider
clock semantics require connected validation before relying on these gates.

The scale observer receives captured executable BBO with original capture time.
Book and price observations share one ordered timeline; trading-worker wall-time
peeks cannot advance the observer ahead of queued books. LL retains its configured
book cadence and repair prices retain worker-frequency updates. Pure replay does
not validate actual QT delivery, scheduling, or source timestamp semantics.

Buffer capacity scales with price/book cadence: 1024 observations at defaults,
roughly 256 seconds, bounded between 256 and 4096 records. Price records do not
contain depth arrays. Only full books count toward warmup and book continuity.
Overflow is explicit loss, never silently accepted continuity. Control and broker
work stay on the existing worker, ahead of bounded book consumption. Each cycle
drains at most 128 capture records so broker reconciliation and controls get
another turn during long catch-up. New risk remains vetoed with queued records.
Quote-event
draining is also bounded so a concurrent producer cannot extend it indefinitely.

## Diagnostics

Checkpoint/metrics include queued and dropped sample counts, oldest drained
sample lag, source ages and capture recovery reason. Decision logs retain
`book_unusable` with BBO/DOM detail, `book_usable_recovered`, and the existing
warmup/reset events. New `evidence_catchup_started` and
`evidence_catchup_completed` events distinguish recovery without a full rewarm.
LL transition `actionable` is false for historical/warming observations.

## Validation and release

The verified release and rollback copies are archived under
`research/out/kahn-catchup-release-20260915/`.
Validation passed: 254 C# checks, 24 transport tests, and a Release build with
zero warnings or errors. The suite includes production queue/gates/clock and
actual LL engine/session checks for both root sides and Lean/Consumed owners.
The release archive contains saved logs and the staging `manifest.json` with
candidate, installed-DLL and runtime-source hashes. These results do not establish
connected QT timestamp quality or broker execution behavior.

The user authorized deployment after the implementation review. ES and NQ
checkpoints reported Stopped, zero position and zero working orders, with no
pending fill/close or recovery reason. The DLL, PDB and dependency manifest were
installed and hash-verified; see `RELEASE_2026-09-15.md` and the archived
`deployment.json`. These checkpoint checks are runtime-local, not a broker audit.
No live controls were sent and Quantower was not restarted.
Connected shadow validation should check source-age behavior, bounded worker
stalls, short mismatch recovery, gap/overflow fallback and actual risk-down
handling before relying on the new adapter with live orders.
