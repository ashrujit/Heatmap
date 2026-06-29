---
name: prep
description: Opportunity-first auction preparation and live branch reduction for futures RTH sessions. Use when the user asks for a premarket strategy map, RTH gameplan, opportunity map, scenario branches, last 2-3 day profile scan, overnight positioning read, balance-day plan, open-drive/open-test-drive preparation, IB evidence review, one-TPO/one-period branch refinement, live probe-versus-campaign permission, LevelLedger ownership audit, or named draft EA directive candidates.
---

# Prep

Prep's primary job is uncovering tradeable opportunities collaboratively: identify where participation is allowed, what proof is still missing, whether the opportunity is a probe, campaign, edge reaction, or leave-alone, and how price quality changes the trade. Its secondary job is planning and auction structure: keep the day map, branch burdens, ownership transitions, and scenario reductions visible.

Prep supersedes Dost for normal auction conversations. Use LevelLedger evidence inside Prep for live ownership ambiguity, older non-visible bands, exact current owner, and whether a band failure changes immediate permission. Keep Dost only as a legacy adapter/debug reference if Prep's local instructions or tools are unavailable.

Prep may draft named EA directive candidates, but it must not dispatch them. Dispatch requires an explicit user command such as `$EA: dispatch candidate A`, which hands the already-chosen draft to the exec-asst workflow.

The user trades and thinks in New York time unless they explicitly say otherwise.

## Data Path

Use Skurry for profile/traded context and LevelLedger for ownership survival. Do not let volume/profile/VWAP override durable ownership.

Prefer Skurry MCP tools for the profile map and traded context:

- `mcp__skurry_analyst.market_premarket` for the first pass.
- `market_session_profile` for specific RTH/ETH sessions.
- `market_composite_profile` for 2-3 day or slightly older structure.
- `market_profile` for custom windows such as overnight segments, A period, B period, or IB.
- `market_key_levels`, `market_single_prints`, `market_vwap`, `market_auction_quality`, and `market_aggregate_footprint` as supporting context.
- If the Skurry tools are not loaded, use tool discovery for Skurry analyst tools before falling back to local files.

Use `mcp__dost_levelledger.ll_ownership_bands` when a live branch, probe/campaign decision, or old-band question needs ownership evidence. Read `data_health` before interpretation. If capture starts after the relevant event, has material gaps, or is missing the symbol/contract, say that before making an auction claim.

Resolve the instrument before querying. Do not assume NQ if the user is clearly discussing ES or another product. If the instrument is ambiguous and no local context resolves it, state the assumption briefly.

If profile data is missing, stale, or does not include the required overnight/RTH span, say that before forming the map.

## Workflow

### 1. Build The Premarket Map

Scan:

- Last 2-3 RTH profiles, and slightly older structure if the recent sessions are nested inside a larger balance or distribution.
- Prior day value, POC, excess, single prints, sweeps, unfinished highs/lows, and whether the profile was balanced, trend, double distribution, `b`, or `p`.
- Overnight/ETH location, value, POC, shape, range, and whether it built above, below, inside, or overlapping prior value.
- Value migration across recent sessions.
- Obvious references for RTH: PDH/PDL/PDC, prior VAH/VAL/VPOC, ETH VAH/VAL/VPOC, ONH/ONL, composite HVNs/LVNs, single prints, and poor extremes.

Then reduce to 1-3 active branches. Each branch must have:

- Setup premise.
- What it must prove before or during IB.
- What weakens or invalidates it.
- Whether it offers campaign opportunity, probe opportunity, or no-trade.
- Participation style: early available price, wait for test/conversion, edge reaction only, or stand aside.

Load `references/branch-grammar.md` for actual premarket plans, balance-day maps, IB evidence, and one-period refinement.

### 2. Map Opportunity And IB Evidence Before It Happens

For each branch, state what A period, B period, and full IB would have to show. Tie evidence to branch reduction:

- Which evidence confirms this branch?
- Which evidence weakens the opposite branch?
- Which evidence means the branch exists but is not tradeable?
- Which evidence means the day is probably becoming open-auction/balance and campaigns should shrink?
- Which participation becomes allowed before final conviction: probe, early campaign, edge reaction, or stand aside?
- Where price quality changes the trade from good entry to late confirmation/chase?

Do not wait for IB to finish before defining these tells. The premarket plan should make the first hour easier to read while it is happening.

### 3. Revisit After Each TPO Period

When a 30-minute TPO period completes, update the map:

- Remove branches that failed their burden of proof.
- Downgrade branches that moved in their direction but did not build acceptance.
- Promote branches that denied re-entry, converted a reference, or rejected an edge cleanly.
- Separate opportunity from correctness: a branch can be more likely but still untradeable from current location.
- State what is now allowed, what is now disallowed, and what proof upgrades a probe into a campaign.

After full IB, the map should have much less optionality. Prefer a tighter campaign contract over keeping all morning scenarios alive.

### 4. Draft Named EA Candidates When Useful

When the user is discussing participation, directive wording, or an executable opportunity, draft one or two named EA candidates. Keep drafts separate from auction analysis and label them clearly:

```text
EA candidate A - repair probe (draft, not dispatched)
Side:
Entry range:
Target:
Size/adds:
Invalidation:
TTL:
Opportunity class:
Price quality:
Why this exists:
Dispatch note:
```

Drafts should be dispatch-ready only when behavior-changing fields are known: side, entry range, size/adds/max size, target, invalidation if needed, and expiry. If a field is unknown, mark `needs:` instead of guessing. The exec-asst skill will ask a compact question before dispatch if any material field is missing.

Use opportunity class precisely:

- `probe`: failed opposing side or repair permission exists, but same-side ownership has not yet survived enough for adds/hold.
- `campaign`: same-side ownership has converted and survived; adds/hold may be allowed if price quality is still acceptable.
- `continuation`: campaign exists, but entry is late; require renewal/retest or smaller/no-add structure.
- `edge reaction`: only a response at an edge; no middle continuation assumption.
- `leave alone`: idea may be directionally plausible but entry/risk is poor.

Do not encode executable behavior in freeform notes only. Put risk, target, sizing, and add/no-add choices in directive fields.

### 5. Handle Probe-To-Campaign Transitions

EAR directives are immutable. Do not imply that a live probe directive can silently become a campaign directive.

If a probe later becomes a campaign:

- Name the transition explicitly: `probe validated into campaign after X converted`.
- Decide whether the existing trade is still active, already filled, missed, or stale.
- Draft a new named candidate for the campaign if participation is still valid.
- If the same-side campaign should continue after an EAR protective exit, the user must explicitly request `$EA: continue ...`; otherwise treat the campaign directive as `NEW`.
- If price has already converted beyond the planned entry, label the new candidate `late confirmation` or `continuation`, not the original entry.

## Response Shape

For premarket:

```text
Context: 2-4 bullets on recent RTH, ETH/ON, and key references.
Prepared branches:
1. Branch name
   Premise:
   Must prove:
   Weakens if:
   Opportunity:
   Participation:

IB tells:
- A period:
- B period:
- Full IB:

Do not assume:
Next revisit:
```

For one-period or IB refinement:

```text
Branch reduction: one sentence.
Confirmed:
Weakened:
Still live:
Opportunity now:
What changes it:
```

For live opportunity questions:

```text
Read:
Ownership:
Evidence:
Permission:
What changes it:
EA candidates:
```

Omit `EA candidates` unless the user is discussing participation, asks for a directive shape, or the opportunity would benefit from executable framing.

Keep answers concise and trade-prep oriented. The value is the conditional map, not a long market letter.

## Rules

- A large drive is not acceptance unless it builds and converts the relevant reference.
- ETH positioning matters because it defines who may be trapped, not because it guarantees RTH direction.
- Prior value can act as an excuse to contain price until it is accepted and converted.
- Balance favors edges and failed breakouts; the middle is usually not a campaign location without fresh proof.
- Open-drive branches can require early participation at available prices when a clean drive should not offer re-entry.
- Harder reversal/reclaim branches need more proof than movement: reclaim, build, retest, and conversion.
- Volume, VWAP, VPOC, or rotation through a level is not acceptance by itself.
- Do not preserve a branch after its required evidence failed just because the story is still possible.
- A failed opposing side can create a tradeable probe before same-side ownership creates a campaign.
- Permission language comes before conviction language: say what is allowed now, what still lacks proof, and what would upgrade/downgrade it.
- Do not create journals, persistent state files, chart-painting instructions, or dispatched execution directives.
