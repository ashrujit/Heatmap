# Prep Branch Grammar

Use this reference when building a premarket opportunity map, mapping IB evidence, planning a balance day, or refining branches after a TPO period.

## Core Branch Set

Keep only the branches that the current structure actually supports. Most mornings should reduce to two or three:

1. Clean drive or open-test-drive in the direction of overnight imbalance.
2. Reclaim or rejection branch against overnight positioning.
3. Open-auction, balance, or edge-search branch when neither side has easy campaign permission.

Each branch needs a burden of proof. Do not treat the branch as valid because price moved in that direction.

## Branch Template

```text
Branch:
Why prepared:
Must prove:
Weakens if:
Invalid if:
Opportunity:
Participation:
First target / owed area:
Danger boundary:
```

Use `opportunity` labels consistently:

- `campaign`: conditions support pressing or holding for a larger auction objective.
- `early campaign`: if real, price should not offer a comfortable retest; available price may be necessary.
- `probe`: participation is valid, but take profits into references and do not assume continuation.
- `edge reaction`: trade only around balance extremes, failed breaks, or clear rejection.
- `leave alone`: branch may be intellectually possible, but current location or proof quality is poor.

## Common Premarket Structures

### ETH Balance Below Prior Value

Example context: prior day was balanced or overlapping prior sessions; ETH builds a `b` profile or balance below prior VAL.

Short drive or OTD short branch:

- Premise: overnight business accepted below prior value, or sellers are pressing a lower distribution.
- Must prove: hold below ETH value or ETH base, deny re-entry into ETH value, and build below the overnight lower edge.
- Strong evidence: pullbacks fail below ETH VAL/VPOC, A period extends lower without repairing back into ETH value, and B period does not reclaim the base.
- Opportunity: `early campaign` if the drive is clean. Waiting for a perfect higher test may miss the trade because the branch should not offer re-entry.
- Weakens if: price re-enters ETH value, repairs the lower distribution, or cannot hold below ETH VPOC.

Long reclaim branch:

- Premise: overnight shorts are trapped below prior value or lower prices were only inventory adjustment.
- Must prove: reclaim ETH base, build above ETH value, then reclaim prior VAL and convert it into support.
- Strong evidence: A/B periods hold above ETH VPOC after reclaim, prior VAL shifts from resistance to support, and pullbacks fail above prior VAL.
- Opportunity: usually `probe` until prior value is reclaimed and converted. A large spike into prior value is not enough.
- Weakens if: prior VAL contains price, the move only tags PD value and returns to ETH value, or fresh demand fails inside prior value.

Balance/open-auction branch:

- Premise: ETH location is important but neither side converts it into RTH ownership.
- Must prove: both drive attempts fail, middle stays fast, and edges become the only clean locations.
- Opportunity: `edge reaction`; avoid campaigns through the middle unless fresh ownership develops.

### ETH Balance Above Prior Value

Invert the proof:

- Long drive must hold above ETH value and deny re-entry.
- Short reclaim must first break ETH base, then re-enter prior value, then convert prior VAH or value edge from support into resistance.
- A downside move that only falls into prior value is not proof until it accepts there and holds failed attempts back above.

### Inside Prior Value

If ETH builds inside prior value, treat the open as balance first unless the open quickly proves otherwise.

- Campaign long needs acceptance above value or a clean failed break below value.
- Campaign short needs acceptance below value or a clean failed break above value.
- Inside the value area, expect rotations and false starts.
- Participation is usually `probe` or `edge reaction` until one side builds outside value and survives retests.

## Balance-Day Map

For overlapping profiles, accepted ranges, or multi-day balance:

- Define balance high, balance low, value center, major HVNs, LVNs, and poor extremes.
- The middle is a poor campaign location unless fresh ownership creates a new distribution.
- Edges matter because they can reject, break, or fail.
- A breakout must build outside the edge and deny re-entry.
- A failed breakout back into balance targets value center, then the opposite edge if acceptance continues.
- A return from an edge to the middle is not automatically a new campaign; it can be simple repair.

Branch set for balance:

```text
1. Accepted breakout
   Must prove: build outside edge, hold retest, deny re-entry.
   Opportunity: campaign only after acceptance; early campaign only if drive is clean and no re-entry.

2. Failed breakout
   Must prove: attempt outside edge fails back inside, then edge converts against the breakout side.
   Opportunity: campaign toward center/opposite edge if failure is clean; otherwise probe.

3. Open auction / edge search
   Must prove: both sides fail, middle stays fast, no durable ownership away from edge.
   Opportunity: edge reactions only; avoid pressing middle continuation.
```

## IB Evidence

Map evidence before the open so the first hour reduces branches instead of creating new stories.

### A Period

Watch:

- Opening location relative to ETH value, prior value, and balance edges.
- Whether the first drive denies re-entry into the area it left.
- Whether movement builds outside a reference or only tags it.
- Whether price returns through the open/VWAP/value without resistance.
- Whether early single prints remain open or repair quickly.

Interpretation:

- Clean drive plus no re-entry supports an `early campaign`.
- Drive into prior value without conversion is only a test.
- Fast return into the prior range weakens open-drive assumptions.
- Two-sided failure promotes open-auction or edge-search.

### B Period

Watch:

- Does B extend A in the same direction or repair A's excess/single prints?
- Does B convert the key reference from resistance to support or support to resistance?
- Does B hold outside ETH/prior value, or pull the auction back into the middle?
- Does a failed A drive create an opposite campaign, or only return to balance?

Interpretation:

- B continuation after A denial strengthens campaign permission.
- B repair of A drive downgrades the branch to probe or failed-drive.
- B acceptance back inside value usually weakens the original drive and promotes balance.

### Full IB

After the first hour:

- IB extension beyond a cleanly accepted edge supports the trend branch.
- Failed IB extension back inside the range supports failed-breakout or balance repair.
- No extension and repeated failures keep campaigns low-quality.
- If both IB extremes are poor or quickly revisited, treat them as unfinished references, not durable extremes.

## One-Period Refinement

At every completed 30-minute period, answer:

```text
Which branch lost required evidence?
Which branch gained required evidence?
Which reference converted?
Which reference contained price?
Is the next opportunity a campaign, probe, edge reaction, or leave alone?
What specific trade idea is now disallowed?
```

Reduce optionality aggressively:

- If price re-entered the area a drive had to deny, the clean drive branch is weakened.
- If price converted a value edge and survived, the reclaim branch strengthens.
- If price keeps rotating through value without survival, campaigns shrink.
- If the only trade requires chasing into the middle of balance, mark it `leave alone`.

## Output Examples

### ETH Below Prior Value

```text
Prepared branches:
1. OTD short below ETH value
   Premise: ETH built below PD VAL; if sellers own it, RTH should not let price back into ETH value.
   Must prove: hold below ETH VAL/VPOC and extend below ETH low without repair.
   Weakens if: A or B re-enters ETH value and holds.
   Opportunity: early campaign if denial is clean.
   Participation: available prices; do not wait for ideal higher retest if drive is accepted.

2. Long reclaim into PD value
   Premise: overnight sellers may be trapped below value.
   Must prove: reclaim ETH base, then convert PD VAL as support.
   Weakens if: PD VAL contains price or the move returns to ETH value.
   Opportunity: probe until PD VAL converts.
   Participation: wait for conversion, not just a large spike.

3. Open auction / edge search
   Premise: neither side converts ETH position into RTH acceptance.
   Must prove: both attempts fail and middle stays fast.
   Opportunity: edge reaction only.
```

### Multi-Day Balance

```text
Prepared branches:
1. Accepted breakout above balance
   Must prove: build above balance high, survive retest, deny re-entry.
   Opportunity: campaign after acceptance.

2. Failed breakout back into balance
   Must prove: outside attempt fails, balance high converts to resistance.
   Opportunity: campaign toward center only if failure is clean; otherwise probe.

3. Open auction inside balance
   Must prove: no edge acceptance, repeated two-way failure.
   Opportunity: edge reaction; leave middle alone.
```
