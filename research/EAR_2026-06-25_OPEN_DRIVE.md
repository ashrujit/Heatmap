# EAR 2026-06-25 Opening Liquidation Drive

Question: would the first liquidation drive have been captured by issuing the
directive earlier, widening the directive, or something else?

## Actual directive

`2026-06-25-directive-short-093251-771f15` was accepted at 09:32:51 ET.

- order range: 30062-30200
- context range: 29750-30200
- target: 29750
- state: armed, evidence ready

It did not enter. At 09:34:24 ET, demand LF `15` held and paused the flat short.
That LF later invalidated at 09:37:33 and the parent demand rail failed at
09:37:36.

## Opening evidence timeline

| ET | event | band | quote/distance | read |
| --- | --- | --- | --- | --- |
| 09:28:40 | supply `12` owned | 30164.00-30164.75 | bid 30155.00, 36 ticks from band | active EAR would set pending retest, not enter immediately |
| 09:28:58 | supply `12` tested | 30164.00-30164.75 | bid 30162.25, 7 ticks from band | earlier active directive could enter short here |
| 09:29:01 | supply `12` held | 30164.00-30164.75 | bid 30158.75, 21 ticks from band | already barely outside direct-retail distance |
| 09:30:03 | supply `12` failed | 30164.00-30164.75 | bid 30177.25 | pre-open entry would likely be stopped on the opening drive |
| 09:30:23 | supply `13` owned | 30158.25-30163.00 | bid 30142.00, 65 ticks from band | first RTH liquidation sponsor formed too far away for direct conversion |
| 09:33:47 | demand `14` formed | 30048.00-30049.50 | bid 30047.25 | lower business begins |
| 09:34:24 | LF `15` held | 30048.00-30049.50 | bid 30062.25 | actual directive pauses while flat |
| 09:37:33 | LF `15` invalidated | 30048.00-30062.75 | bid 30044.50 | pause clears in short direction |
| 09:37:36 | demand `14` failed | 30048.00-30049.50 | bid 30040.75 | no nearby same-side supply support, so no supported reclaim entry |
| 09:40:17 | supply `19` owned | 29999.75-30003.00 | bid 29979.50, 81 ticks from band | new sponsor emerges far away; direct conversion waits for a retest |

## What-if reads

### Earlier directive

If the directive had been active before 09:29 and allowed to trade pre-open,
EAR likely could have entered the supply `12` retest around 09:28:58. That is
not obviously desirable: supply `12` failed into the 09:30 open and would
probably have been a losing first attempt.

If the directive had been active before open but `not_before=09:30`, it still
probably would not catch the first RTH drive. Supply `13` owned at 09:30:23, but
the executable short quote was already 65 ticks below the sponsor band. Current
direct conversion caps this at 20 ticks and would only wait for a retest.

### Wider directive

Wider context was not the primary miss. The actual first directive already had
context down to 29750 and order range down to 30062. The later reissue lowered
the order range to 29968. Even with that wider lower bound, the 09:40 supply
ownership was 81 ticks away from executable price, so direct conversion still
would not fire.

Widening the price envelope only helps if price returns close enough to the
sponsor. In this drive, the auction did not return; it kept repricing lower.

### Something else

The missing mode is not mid-move leverage. It is a one-shot opening-drive /
liquidation-drive entry model that would be explicitly different from normal
campaign entry:

- pre-committed directive before the drive, not a late reaction after price has
  already displaced;
- strict price envelope and target/risk boundaries;
- no add/leverage expectation;
- entry allowed only on a specific opening rejection/liquidation trigger, or on
  a pause-release whose clear is still inside an approved continuation envelope;
- if missed, no chase.

This is a different contract than normal EAR ownership/retest/reclaim. Normal
EAR did what it was designed to do: it refused to sell far below a newly owned
sponsor and waited for a retest that never came.

## Current conclusion

For June 25's initial liquidation drive:

- "Earlier" only works if it is early enough to catch a pre-open retest, and
  that particular pre-open retest likely would have failed.
- "Wider" does not solve the miss by itself because the distance-to-sponsor
  guard remains the binding constraint.
- The plausible missing tool is a separate opening-drive directive contract,
  not a tweak to normal sponsor/retest mechanics.

That contract should be researched as an explicit mode before any runtime
change, because otherwise it becomes a chase rule disguised as evidence.
