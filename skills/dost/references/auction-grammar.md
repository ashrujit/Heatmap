# Auction Grammar

Use this vocabulary to keep Dost's reads consistent.

## Durable Band

A demand or supply row that survives meaningful tests long enough to become usable evidence. Durability is contextual: a fast open may need only a sharp retest and hold, while a slow IB range needs repeated proof and time.

Do not call a newly printed row durable until it has either survived a test, forced price to prove at worse prices, or remained active through enough rotation that traders could lean on it.

## Owner

The side currently controlling the leg or range because its durable bands are holding, or because repeated opposing attempts have failed and price is proving away from those failures.

Owner states:

- `longs own`: durable demand is holding and supply attempts fail above it.
- `shorts own`: durable supply is holding and demand attempts fail below it.
- `contested`: both sides have recent claims, or neither side has survived enough to own.
- `no durable owner`: movement exists, but ownership has not been built.

Avoid owner language when the evidence is only rotation, VPOC, VWAP, or traded volume.

## Meaningful Fail

A meaningful fail is an opposing ownership attempt that mattered enough to attract participation before it failed. It can fuel the next move because traders who leaned on it are now wrong.

Not every tiny band failure is meaningful. Prefer fails that:

- lived long enough to be seen and used,
- formed near a reference or contested region,
- were tested and then lost,
- caused price to prove at worse prices after failure.

## Acceptance

Acceptance means a side can hold ownership after tests and keep proving price away from contested ground.

Acceptance does not mean:

- price traded above or below a reference,
- VPOC migrated or stayed somewhere,
- volume accumulated at a level,
- VWAP was reclaimed or lost once.

Those can support the read, but durable ownership decides it.

## Trade Permission

Use three posture labels:

- `campaign`: evidence is strong enough to add, hold, or press if tests keep holding.
- `probe only`: direction is plausible, but durable ownership has not formed or the owner can still be wrong nearby.
- `stand aside`: read is too contested or the risk point is unclear.

The same direction can move from probe to campaign only after ownership survives. A failed opposing band can justify a probe; durable same-side ownership justifies a campaign.

## Owed Work

State what the auction still has reason to do:

- test a surviving band,
- repair a failed band,
- revisit an extreme,
- finish liquidation into ON/ETH/open/IB references,
- migrate value only after durable ownership supports it.

If nothing durable exists inside a leg and the first same-side band holds, price often has no reason to stop until an extreme or old reference is reached.

## Example Phrasing

```text
Read: The sell leg was contested until demand around 102 failed; short control became cleaner only after 949 supply printed and held.
Ownership: contested first, then short lean.
Evidence: 102 demand lived long enough to matter before failing; 052 demand failed almost immediately; 949 supply became the first durable short lean.
Permission: Shorts before 949 were probes into failed demand, not a full campaign. After 949, shorts can campaign only while tests below open keep holding.
What changes it: durable demand above 949/904 that survives a retest would invalidate the short ownership read.
```

## Example Bias Challenge

```text
I would not call that accepted higher yet. Price traded higher, but the open demand failed almost immediately and the later supply failures did not convert into durable demand. Until demand survives above the pre-open/news range, longs are probes and failed demand can still rotate the auction back toward ON/ETH references.
```
