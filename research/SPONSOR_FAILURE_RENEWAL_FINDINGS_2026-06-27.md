# Sponsor Failure Renewal Findings - 2026-06-27

## Scope

This focused pass follows the practical implication from Thesis 1 and Thesis 3:

- EAR exits strictly on sponsor failure.
- If retries remain, it waits for a fresh seeded event.
- If the sponsor failure was fake and the sponsor side renews at/near the failed area, the later retry seed may be materially worse.

Inputs:

- MarketRecorder `NQU6` only.
- Sessions: `2026-06-23`, `2026-06-24`, `2026-06-25`, `2026-06-26`.
- Window: `09:30-16:00` ET.
- Synthetic LL/EAR ownership grammar only.
- No live EAR logs from the mixed MNQ/NQ period.

Output files:

- `research/out/sponsor_failure_renewal_probe_nqu6_20260623_20260626.csv`
- `research/out/sponsor_failure_renewal_probe_nqu6_20260623_20260626.md`

## Definitions

For every synthetic sponsor `FAIL`, the probe looks for same-side renewal within:

- 180 seconds
- 24 ticks from the failed sponsor band

Renewal types:

- `direct_conversion`: same side renews through a consumed opposite-side band.
- `fresh_ownership`: same side forms a fresh ownership band.
- `hold`: same side holds a nearby structure.
- `none`: no nearby same-side renewal.

Positive `worse_ticks` means worse for the sponsor side: higher for demand, lower for supply.

## Main Counts

Across 479 sponsor failures:

- Near same-side renewals: 84 / 479 = 17.5%.
- Direct-conversion renewals: 22 / 479 = 4.6%.

This means the fake-failure/reclaim situation is not dominant, but it is common enough to matter if the cost of strict exit/retry is large.

## Price Penalty

Near same-side renewals:

- median renewal worse ticks: 58.5
- p75: 82.0
- p90: 119.0

Direct-conversion renewals:

- median renewal worse ticks: 75.5
- p75: 100.0
- p90: 116.0

Read:

- When the pattern appears, the later/re-entry location can indeed be materially worse.
- This supports the user's practical concern: strict sponsor failure plus "wait for new seed" can abandon the best location in fake-failure cases.

## Post-Renewal Consequence

Post-renewal outcomes:

| renewal kind | n | sponsor renewed | sponsor destroyed opposite | opposition renewed | sponsor failed again | no follow-through |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| direct conversion | 22 | 7 | 0 | 8 | 5 | 2 |
| fresh ownership | 38 | 13 | 6 | 8 | 8 | 3 |
| hold | 24 | 16 | 1 | 3 | 4 | 0 |

Read:

- Direct-conversion renewal is the clean conceptual tie to Thesis 1, but in this broad sponsor-failure population it is rare and mixed.
- Nearby `hold` renewal looked cleaner in this pass.
- Fresh ownership renewal had some continuation consequence, including 6 cases where the sponsor side later destroyed opposite structure.

## Practical Interpretation

This does not justify weakening the positioned sponsor-failure flatten rule yet.

It does justify researching a post-failure hysteresis/retry policy:

- Flatten can still happen on mechanical sponsor failure.
- Do not immediately treat the failed sponsor side as dead if same-side renewal appears nearby within a short window.
- If renewal is direct conversion, hold, or fresh ownership near the failed sponsor, preserve a "renewal watch" state instead of waiting blindly for a much later seed.
- A re-entry or invalidation decision should then depend on whether opposition renews, the sponsor fails again, or the sponsor side builds another ownership object nearby.

## Current Takeaway

The user's practical concern is valid as a failure mode, but the strongest near-term hook is not "direct conversion always saves the sponsor."

The stronger hook is:

- sponsor failed,
- same side renews nearby,
- later fresh seed is materially worse,
- therefore EAR should probably distinguish terminal sponsor failure from renewal-watch sponsor failure.

That policy should be tested as a replay rule before touching runtime behavior.

## Refinement After Review

The expected renewal object is probably not a direct conversion immediately after sponsor failure.

More likely pattern:

- short continuation sponsor fails;
- another same-side supply band appears just beyond/above the failed sponsor;
- that new supply band is not tested for some time;
- the failed area may later be revisited, allowing trapped shorts or late exits to clear.

Long side mirror:

- long continuation sponsor fails;
- another same-side demand band appears just beyond/below the failed sponsor;
- that new demand band remains untested for some time.

This suggests two follow-up labels:

- `beyond_same_side_band`: same-side ownership band forms beyond the failure in the adverse direction.
- `failure_area_revisited`: price later trades back through the failed sponsor area, which may separate true terminal failure from fake failure / renewal.

The first renewal probe grouped too many renewal types together. The next pass should separate same-side fresh bands beyond failure from direct conversion, hold, and overlapping renewal.

## Refined Beyond-Failure Pass

The probe was updated to label the more likely renewal object:

- `same-side band beyond failure`: same sponsor side forms an ownership/consumed band beyond the failed sponsor in the adverse direction.
- `fresh same-side band beyond failure`: same-side `OWNED` band from normal same-side lean, not direct conversion.
- `beyond band untested`: the beyond band does not print a `TEST` transition for at least 180 seconds.
- `failure area revisited`: mid trades back inside the failed sponsor band plus 4 ticks within 10 minutes.

Counts across 479 sponsor failures:

- same-side bands beyond failure: 54 / 479 = 11.3%.
- fresh same-side bands beyond failure: 33 / 479 = 6.9%.
- beyond bands untested for at least 180 seconds: 14 / 54 = 25.9%.
- failure area revisited: 418 / 479 = 87.3%.

Price/location penalty:

- beyond-band worse ticks: median 49.5, p75 65.0, p90 83.0.
- fresh-beyond median was about 50 ticks worse.
- untested-beyond median was about 63.5 ticks worse.

Outcome by beyond-band class:

| beyond class | n | sponsor renewed | opposition renewed | sponsor failed again |
| --- | ---: | ---: | ---: | ---: |
| any same-side band beyond | 54 | 33 | 15 | 6 |
| fresh same-side band beyond | 33 | 19 | 11 | 3 |
| untested beyond band | 14 | 7 | 6 | 1 |

Read:

- The exact pattern exists and is not just theoretical.
- It is not dominant, but when it appears the location penalty is large enough to care about.
- The "untested for some time" subset is smaller and mixed; it should not become a standalone rule.
- The useful runtime concept is still a watch state, not automatic re-entry.

## Failure Area Revisit

The failed sponsor area was revisited in 418 / 479 cases, with median revisit delay about 22 seconds.

This partly supports the intuition that true failure often revisits the failed area, but the label is not discriminating enough by itself:

- revisited cases split between sponsor renewed and opposition renewed almost evenly;
- non-revisited cases were much less likely to show sponsor renewal.

Current read:

- A revisit is common auction mechanics, not proof of true failure.
- Lack of revisit is more informative than revisit: if price never comes back to the failed area, the old sponsor is less likely to repair nearby.
- Revisit should be context for exit/re-entry quality, not a standalone classifier.
