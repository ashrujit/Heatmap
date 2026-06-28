---
name: prep
description: Premarket auction preparation for futures RTH sessions. Use when the user asks for a premarket strategy map, RTH gameplan, opportunity map, scenario branches, last 2-3 day profile scan, overnight positioning read, balance-day plan, open-drive/open-test-drive preparation, IB evidence review, or one-TPO/one-period branch refinement.
---

# Prep

Prep builds the premarket opportunity map before RTH and refines it as early TPO periods complete. Its job is branch reduction: identify the few campaigns worth preparing for, what each must prove, what evidence weakens alternatives, and which opportunities are tradeable versus best left alone.

Prep is not Dost. Use Dost for live ownership ambiguity, older non-visible LevelLedger bands, exact current owner, or whether a band failure changes immediate permission. Prep may consult LevelLedger after the open, but only to decide whether a premarket branch is proving or failing.

The user trades and thinks in New York time unless they explicitly say otherwise.

## Data Path

Prefer Skurry MCP tools for the profile map:

- `mcp__skurry_analyst.market_premarket` for the first pass.
- `market_session_profile` for specific RTH/ETH sessions.
- `market_composite_profile` for 2-3 day or slightly older structure.
- `market_profile` for custom windows such as overnight segments, A period, B period, or IB.
- `market_key_levels`, `market_single_prints`, and `market_vwap` as supporting context.
- If the Skurry tools are not loaded, use tool discovery for Skurry analyst tools before falling back to local files.

Use `mcp__dost_levelledger.ll_ownership_bands` only when the branch question needs LevelLedger ownership evidence after RTH starts. Do not turn Prep into a live band-by-band audit.

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

### 2. Map IB Evidence Before It Happens

For each branch, state what A period, B period, and full IB would have to show. Tie evidence to branch reduction:

- Which evidence confirms this branch?
- Which evidence weakens the opposite branch?
- Which evidence means the branch exists but is not tradeable?
- Which evidence means the day is probably becoming open-auction/balance and campaigns should shrink?

Do not wait for IB to finish before defining these tells. The premarket plan should make the first hour easier to read while it is happening.

### 3. Revisit After Each TPO Period

When a 30-minute TPO period completes, update the map:

- Remove branches that failed their burden of proof.
- Downgrade branches that moved in their direction but did not build acceptance.
- Promote branches that denied re-entry, converted a reference, or rejected an edge cleanly.
- Separate opportunity from correctness: a branch can be more likely but still untradeable from current location.

After full IB, the map should have much less optionality. Prefer a tighter campaign contract over keeping all morning scenarios alive.

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
- Do not create journals, persistent state files, chart-painting instructions, or execution directives.
