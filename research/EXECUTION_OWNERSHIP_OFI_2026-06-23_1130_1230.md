# Execution Ownership + OFI — 2026-06-23 11:30–12:30

## Objective

Audit the live EAR long campaigns and LL ownership/HF objects through the
11:30–12:30 New York auction, then ask whether event OFI would improve:

1. entry timing and location;
2. add timing and weighted-BE exposure;
3. sponsor promotion and position continuity;
4. false-positive and false-negative local HFs.

The user's framing is retained: seller/high-auction failure inside this window
can be local without invalidating the larger long leg.

## Data Health And Inputs

- NQU6 MarketRecorder events, canonical snapshots, and ticks.
- 25,617,518 event rows replayed through 12:30.
- Zero continuity gaps; 77 repair-triggering events.
- Exact EAR JSONL order, fill, sponsor, directive, and evidence timestamps.
- Runtime LL transitions were used for execution decisions; the offline replay
  was used to audit surrounding ownership/HF objects.

The event log does not persist the accepted directive's entry/context/add price
ranges. It proves when a directive was armed and whether an intent was emitted,
but it cannot independently prove which exact range rejected an otherwise
eligible resolution. The user's report that price escaped a constrained range
is consistent with the absence of order intents after valid demand objects, but
remains an inference. Future `directive_accepted` telemetry should include the
normative ranges.

## Actual Execution Sequence

| Time | Runtime action | Result |
|---|---|---|
| 11:27:49 | Base long 2 @ 29724.50, consumed demand 29717.25–29719.00 | Position active entering fixture |
| 11:30:50 | Add 1 @ 29736.25 on consumed demand 29729.50–29732.00 | Weighted BE installed at 29728.50 |
| 11:38:17 | Weighted BE fills @ 29728.25 | Entire three-lot campaign flat |
| 11:40:46 | Reissue base long 2 @ 29713.75, consumed demand 29706.50–29708.50 | Strong structural base |
| 11:45:38 | Sponsor promoted to lean demand 29731.75–29732.50 | New sponsor had not proved a durable retest |
| 11:45:50 | Promoted sponsor fails; flat @ 29724.50 | Prior consumed sponsor had not failed |
| 11:49:21 | Supply HF 29752.50–29757.25 | Prior directive invalidated while flat |
| 11:50:19 | New long directive accepted | No order intent before 12:00 HF |
| 12:00:23 | Supply HF 29800.50–29803.25 | Directive invalidated; parent supply fails 13 sec later |
| 12:05:30 | New long directive accepted | Invalidated by 12:07 HF |
| 12:07:12 | Supply HF 29857.75–29873.00 | Supply complex later fails as auction continues higher |
| 12:16:14 | Supply HF 29904.50–29909.25 | Followed by current consumed-demand failure at 12:16:44 |

## What OFI Actually Said

### The 11:30 add

OFI supported the 29729.50–29732.00 consumed-demand band when it became owned:

- 11:30:46 event OFI 3s/5s: `+3.6 / +31.1`.

At the actual add/retest four seconds later it had reversed sharply:

- 11:30:50 event OFI 3s/5s: `-46.9 / -47.0`.

The add immediately converted the campaign to weighted-BE protection. Two
nearby demand objects had resolved within ten seconds, but the consumed object
was a distinct root formed after the prior fill and therefore passed the
existing epoch guards. Later review did not support adding a spatial-clearance
or universal post-ownership test/hold rule: this was an atypical outcome from a
non-primary campaign, while the current causal epoch rules have worked normally
in the campaign fixtures. OFI reversal at the retest is descriptive, not a
validated reason to defer leverage.

### The good 11:40 base disproves a directional OFI rule

The 29706.50–29708.50 consumed-demand sponsor was attacked at entry:

- 11:40:46 event OFI 3s/5s: `-45.4 / -33.6`.
- Price tested down to the sponsor area, then held at 11:40:58 and 11:41:08.
- The next two-minute favorable excursion was 74 ticks; the next ten-minute
  favorable excursion was 165 ticks.

A rule requiring positive OFI would reject this good long. The useful evidence
was negative flow attacking demand **plus failure to trade through it**. This is
absorptive ownership, distinct from initiative ownership where favorable OFI
and displacement agree.

### The 11:45 sponsor promotion does not justify a lineage change

The lean 29731.75–29732.50 demand band had positive OFI when promoted:

- 11:45:38 event OFI 3s/5s: `+30.3 / +11.5`.

Seven seconds later its first test carried `-30.4 / -71.2`; it failed five
seconds after that. OFI at formation did not forecast the failure. This single
exit does not establish that promoting newly owned lean demand was a policy
error. In the later long, the same promotion machinery advanced to lean
demand near 29689.75-29690.50 and produced the correct exit near 29681 when that
sponsor failed.

## Discarded Sponsor-Lineage Counterfactual

A narrower policy can improve this fixture in hindsight:

1. Initial filled support remains the sponsor.
2. Consumed demand may promote after accepted displacement.
3. Lean demand cannot replace the sponsor until it survives meaningful
   post-ownership tests; raw favorable OFI is insufficient.
4. During a test, opposing OFI plus a hold is absorptive evidence, not automatic
   disqualification.

Applied to the 11:40 base:

- Block the 11:45 lean promotion; retain consumed demand 29706.50–29708.50.
- Promote consumed demand 29724.50–29726.00 at 11:50:44. It had aligned OFI
  `+38.4 / +49.8` and did not fail in the fixture.
- Later promote repeatedly tested consumed demand 29896.25–29898.00. It was
  attacked with negative OFI, held repeatedly, then failed at 12:16:44 with OFI
  `-27.5 / -46.1`.

Combined with local-first HF handling, this lineage keeps the campaign through
the 11:49, 12:00, and 12:07 local HFs, then supplies a contemporaneous
structural exit near 12:16. The mechanical counterfactual is approximately
29713.75 to 29890.25 (`+176.5` points) for the base position instead of the
actual 29713.75 to 29724.50 (`+10.75` points). That difference is a hindsight
fixture result, not an expected-PnL estimate, and the later long demonstrates
why this promotion restriction should not be implemented.

## Earlier Entry After 11:50

The 11:50 directive was armed before supply candidate 93 converted into demand:

- 11:50:33 adverse displacement began near 29729 with event OFI 3s/5s around
  `+57 / +62`.
- At +3 seconds, price was about 29738 and OFI remained strongly aligned.
- Normal ownership printed at 11:50:44 with price about 29741.75.

An initiative-OFI early gate could have authorized entry several points before
normal ownership confirmation and before further price escape. A second similar
opportunity occurred at 11:56:28–11:56:39: favorable demand displacement and
OFI appeared around 29766–29776 before ownership printed near 29783.

Because historical directive ranges are absent from JSONL, this study cannot
prove the earlier price was inside each directive. It does prove that the
runtime saw no order intent despite these demand transitions.

## HF Audit

| HF | OFI 3s/5s | Subsequent behavior | Interpretation |
|---|---:|---|---|
| 11:49:21 supply 29752.50–29757.25 | -46.2 / -45.6 | -104.5 ticks within 2m, then +289 ticks within 10m | Valid local high failure; not a long-thesis reversal |
| 12:00:23 supply 29800.50–29803.25 | -35.5 / -48.2 | No lower excursion over 2m; parent supply failed 13s later; +207 ticks | False terminal HF despite aligned OFI |
| 12:07:12 supply 29857.75–29873.00 | -18.6 / -3.2 | Two-sided local response; supply rails failed by 12:10; +247 ticks within 10m | Weak/local HF; terminal invalidation too strong |
| 12:16:14 supply 29904.50–29909.25 | -10.7 / -24.0 | Current consumed demand failed at 12:16:44; -87.5 ticks within 2m | Sponsor-aligned terminal failure |
| 12:20:23 supply 29858.50 | -5.7 / +0.6 | Mixed OFI inside post-failure auction | Not an independent terminal read |

The failure is semantic as much as statistical. `HF_while_flat` currently
invalidates the directive immediately. In this fixture, HF should pause new
entry while its local owner is tested. It should terminate a long thesis only
when the current demand sponsor also fails, or when a separate persistence and
acceptance rule proves the failure is not merely local.

## Possible False-Negative HFs

A permissive discovery screen selected the lower 20% of five-second event OFI,
required negative three- and five-second OFI near a five-minute high, excluded
existing HFs within 15 seconds, and then labeled the fixture using a 30-second
down response. It found:

| Time | Price | OFI 3s/5s | 30s down/up |
|---|---:|---:|---:|
| 11:52:11 | 29782.25 | -19.6 / -32.5 | -44 / +25 ticks |
| 11:54:31 | 29817.50 | -11.1 / -28.4 | -102.5 / -17 ticks |
| 12:01:39 | 29845.75 | -10.6 / -27.7 | -38.5 / -3.5 ticks |

The 11:54 case is the clearest missing local HF: no z-qualified supply band
formed, while negative flow at the local high preceded a 25-point rejection.
These are retrospective discovery candidates, not a deployable OFI threshold.
They support adding an accumulation/response path alongside z-score discovery.

## Resulting Ownership Model

The fixture argues for two ownership paths:

- **Initiative ownership:** aligned OFI and favorable displacement allow earlier
  qualification, as at 11:50 and 11:56.
- **Absorptive ownership:** opposing OFI attacks a zone, but repeated tests fail
  to trade through and the level repairs, as at 11:40 and later 12:11–12:16.

Z-score remains an abnormality detector. OFI describes signed pressure. Price
response and resiliency decide whether that pressure created, attacked, or
failed to transfer ownership.

## Revised Policy Conclusions

1. Leave sponsor promotion unchanged. Favorable-only, non-overlapping handoff
   produced the correct semantic exit in the later long.
2. Leave add/epoch qualification unchanged. Existing causal-root freshness and
   one-attempt guards are deliberate; this fixture does not justify a spatial
   clearance or universal retest rule.
3. HFs while flat: pause eligibility, do not immediately invalidate the
   directive. Clear the pause if the HF's parent owner fails.
4. HFs in position: flatten only when the current same-side sponsor fails or
   the HF satisfies an explicit broader acceptance rule.
5. Telemetry: persist accepted directive ranges so price-constraint misses are
   auditable.
6. Keep OFI paths experimental until multi-session evidence exists.

Implemented 2026-06-23 without altering sponsor or epoch policy. Continued
shadow/live audit should count position continuity, missed true failures, and
local-HF pause duration.

## Reproduction

```powershell
uv run --with polars --with numpy --with tzdata python `
  .\LevelLedger\research\execution_ownership_ofi_fixture.py `
  --date 2026-06-23 --symbol-dir NQU6 --window 11:30-12:30 `
  --context-min 5 --out-dir C:\Heatmap\research\out
```

Artifacts:

- `research/out/execution_ownership_ofi_2026-06-23_1130-1230.txt`
- `research/out/execution_ownership_ofi_2026-06-23_1130-1230_events.csv`
- `research/out/execution_ownership_ofi_2026-06-23_1130-1230_grid.csv`
