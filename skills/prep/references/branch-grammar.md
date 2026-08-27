# Prep Branch Grammar

Use this reference for premarket maps, balance days, IB evidence, one-period refinement, and live opportunity discussion.

## Core Branch Set

Keep only branches supported by current structure. Most mornings reduce to two or three:

1. Clean drive or open-test-drive in the direction of overnight imbalance.
2. Reclaim or rejection against overnight positioning.
3. Open-auction, balance, or edge-search when neither directional branch proves itself.

Each branch needs a burden of proof, an early useful tell, and a falsifier. Movement alone does not validate it.

## Branch Template

```text
Branch:
Why prepared:
Must prove:
Earliest sufficient evidence:
Weakens if:
I am wrong if:
Opportunity:
Participation character:
Natural objective:
Confirmation cost:
```

Use opportunity labels consistently:

- `early campaign`: if real, price should not offer comfortable re-entry; available price may matter.
- `campaign`: acceptance supports pressing or holding for a larger auction objective.
- `probe`: the failure or repair is tradeable, but evidence does not support assuming full continuation.
- `edge reaction`: the opportunity exists only around a balance extreme, failed break, or clear rejection.
- `no meaningful opportunity`: direction may be intellectually plausible, but remaining path, price quality, or session conditions are poor.

## Opportunity Lifecycle

Label prospective opportunities so a conditional opinion is not mistaken for a trade instruction:

```text
smelled -> forming -> active -> completed
                    \-> falsified
```

- `smelled`: structure creates plausible asymmetry, but price has not reached the decision point.
- `forming`: price is testing the reference or condition that can activate the idea.
- `active`: the specified failure, acceptance, or conversion has occurred and meaningful path remains.
- `falsified`: the observable `I am wrong if` condition occurred. Remove the idea immediately.
- `completed`: the natural auction objective traded or most of the intended path was consumed.
- `absent`: no side has a coherent opportunity worth ranking.

Never upgrade lifecycle merely because later evidence looks more certain. Confirmation can arrive after the original opportunity is completed.

## Proof Versus Price Quality

Track both clocks:

```text
Evidence increases -> directional confidence can improve
Price travels      -> remaining opportunity can deteriorate
```

For every live hypothesis distinguish:

- `earliest sufficient evidence`: enough auction information to make the hypothesis real.
- `stronger confirmation`: useful evidence that may arrive later, such as VWAP recapture or broader acceptance.
- `confirmation cost`: distance, target path, or clean price already consumed while waiting.
- `opportunity expiry`: reference or objective after which the original idea is late or completed.

Do not require complete directional control before naming a responsive trade. Do not call a fully confirmed move attractive when it is entering developing HVN/VPOC churn or has already reached its natural objective.

## Chase And Bias Audit

Run this before recommending that the user reinterpret a one-way move as urgent participation:

```text
What was the prepared burden of proof?
What evidence has actually appeared?
What easier evidence is being substituted because the move was missed?
Is price truly escaping, or is the decision point still ahead?
If the move leaves without acceptable participation, is that simply a missed trade?
What opposing opportunity becomes visible once urgency is removed?
```

Common story substitutions:

- Open reclaim treated as proof of acceptance above ETH value.
- VWAP buying treated as proof that an upper edge will convert.
- Thirty minutes of one-way repair treated as a new campaign when it is approaching its natural test.
- Strong confirmation near the opposite edge treated as a fresh entry rather than completion.

Name the substitution directly without taking ownership of the user's trade decision.

## Common Premarket Structures

### ETH Balance Below Prior Value

Short drive or OTD short:

- Premise: overnight business accepted below prior value, or sellers are pressing a lower distribution.
- Must prove: hold below ETH value/base, deny re-entry, and build below the overnight lower edge.
- Early tell: pullbacks fail below ETH VAL/VPOC and A period extends without repair.
- Opportunity: `early campaign` when denial is clean.
- Weakens if: price re-enters ETH value, repairs the lower distribution, or cannot hold below ETH VPOC.
- Wrong if: the area the drive had to deny is reclaimed and accepted.

Long reclaim:

- Premise: overnight shorts are trapped below value or lower prices were inventory adjustment.
- Must prove: reclaim ETH base/value, then reclaim and convert prior VAL or the relevant upper ETH reference.
- Early tell: the failed lower drive repairs important references without deep selling on retest.
- Opportunity: `probe` during repair; `campaign` only after the prepared conversion.
- Weakens if: the upper reference contains price or the move only tags it and returns.
- Wrong if: the repair base fails and sellers rebuild below it.

Open auction / edge search:

- Premise: neither directional branch converts ETH location into RTH acceptance.
- Must prove: both drive attempts fail, the middle stays rotational, and edges become the clean decision points.
- Opportunity: rank the best developing edge failure even while current action is `wait`.
- Wrong if: one side builds beyond an edge and denies re-entry.

### ETH Balance Above Prior Value

Invert the proof:

- Long drive must hold above ETH value and deny re-entry.
- Short reclaim must break ETH base, re-enter prior value, and convert the relevant edge into resistance.
- A downside move that merely enters prior value is not proof until it accepts and survives attempts back above.

### Inside Prior Value

Treat the open as balance first unless it quickly proves otherwise.

- Campaign long needs acceptance above value or a clean failed break below value.
- Campaign short needs acceptance below value or a clean failed break above value.
- Inside value, expect rotations and false starts.
- Rank edge reactions over middle continuation until a new distribution builds outside value.

## Balance-Day Map

For overlapping profiles, accepted ranges, or multi-day balance:

- Define balance high/low, value center, major HVNs/LVNs, and poor extremes.
- The middle is a poor campaign location unless a new distribution builds there.
- A breakout must build outside the edge and deny re-entry.
- A failed breakout back into balance targets value center, then the opposite edge if acceptance continues.
- A return from an edge to the middle can be repair rather than a new campaign.

Branch set:

```text
1. Accepted breakout
   Must prove: build outside edge, survive retest, deny re-entry.
   Opportunity: campaign while meaningful external path remains.

2. Failed breakout
   Must prove: outside attempt fails and the edge converts against the breakout side.
   Opportunity: campaign toward center/opposite edge if early and clean; otherwise probe.

3. Open auction / edge search
   Must prove: repeated two-way failure and no acceptance away from value.
   Opportunity: smell and rank edge failures; expect middle churn.
```

## IB Evidence

Define these tells before the open.

### A Period

Watch:

- Opening location relative to ETH value, prior value, and balance edges.
- Whether the first drive denies re-entry or only travels quickly.
- Whether movement builds outside a reference or merely tags it.
- Whether price returns through the open/VWAP/value without resistance.
- Whether early single prints remain open or repair.

Interpretation:

- Clean drive plus denial supports an `early campaign`.
- Drive into prior value without conversion is a test.
- Fast return into the prior range weakens the drive.
- Two-sided failure promotes open-auction and moves opportunity toward the edges.

### B Period

Watch:

- Whether B extends A or repairs A's excess/single prints.
- Whether the key reference converts or contains price.
- Whether B holds outside ETH/prior value or returns to the middle.
- Whether a failed A drive creates an opposite opportunity or only balance repair.

Interpretation:

- B continuation after A denial strengthens the campaign.
- B repair downgrades the original drive and can create an opposite probe.
- Acceptance back inside value usually promotes balance.

### Full IB

- Extension beyond a cleanly accepted edge supports the trend branch.
- Failed extension back inside supports failed-breakout or balance repair.
- Repeated failures keep campaigns low-quality but can improve edge asymmetry.
- Quickly revisited IB extremes remain unfinished references.

## One-Period And Live Refinement

At each completed period or meaningful live question answer:

```text
Opinion:
Opportunity lifecycle:
Which branch lost evidence?
Which branch gained evidence?
What did the move prove?
What did it not prove?
What tempting inference may be substituting for the original burden?
What is the best prospective opportunity?
What is the earliest sufficient evidence?
What does waiting for stronger proof cost?
I am wrong if:
If wrong, what becomes the next question?
```

Reduce optionality aggressively, but do not confuse `current action is wait` with `no prospective opportunity exists`.

## Failed Drive And Repair Sequence

When a drive fails to continue, separate these states:

1. `Original campaign active`
   - Required denial still holds.
   - Same-direction continuation remains the best opportunity while path remains.

2. `Original campaign weakened or falsified`
   - The drive reached an objective but did not accept, or price reclaimed what it had to deny.
   - Do not sell/buy the first repair touch as though the original drive remains intact.

3. `Repair opportunity`
   - Failed continuation allows repair toward the next owed reference.
   - Do not confuse repair with full opposite acceptance.

4. `Opposite-edge decision`
   - If repair approaches the other edge, smell both resolutions before they occur.
   - Failure there can activate a responsive move back through the range.
   - Acceptance beyond it falsifies the responsive hypothesis and promotes the breakout/reclaim branch.

5. `HVN/VPOC churn`
   - If neither edge resolves and volume builds in the middle, remaining directional opportunity deteriorates.
   - Later confirmation through the middle may carry higher churn and stop exposure.

Do not wait for the opposite side to demonstrate total control before naming its opportunity. The point is to identify the hypothesis before its path is consumed.

## Session Clock And Energy

Time of day changes whether a structurally valid branch can still develop:

- Early session: sufficient time and energy may remain for a failed edge to rotate through IB.
- After an extended one-way move: distinguish fresh initiative from a mature move reaching its natural test.
- Late morning/lunch: repeated VPOC/HVN formation can make direction correct but participation costly.
- Late session: ask whether the required build, retest, and target path can realistically complete before close.

State whether the scenario has enough time and auction energy. Do not use time of day as a generic reason to avoid an opinion.

## Disagreement Protocol

Treat disagreement as an invitation to refine:

```text
My current claim:
Premise under dispute:
Evidence for the user's interpretation:
Evidence against it:
Observation that separates the two:
What would change my mind:
```

Do not surrender the view merely because the user proposes another side. Equally, do not defend it after its falsifier occurs. Productive disagreement should expose whether the user is trading the prepared branch, an anticipatory version of it, or a newly substituted story.

## Execution Candidate Grammar

Only load this section into the response when the user explicitly asks for directive wording or an executable candidate.

```text
Execution candidate A - [probe/campaign/continuation/edge reaction] (draft, not dispatched)
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

- Name every candidate.
- Mark unknown behavior-changing fields with `needs:`.
- A probe is usually base-only/no-add unless explicit defaults and structure justify otherwise.
- A campaign may allow adds only after its auction conversion survives.
- A continuation candidate must warn when the ideal opportunity has passed.
- Translate context phrases into concrete ranges or mark `needs: entry range`.
- Treat probe and campaign as separate immutable runtime contracts.
