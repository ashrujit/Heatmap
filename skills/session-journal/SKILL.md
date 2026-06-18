---
name: session-journal
description: End-of-day trading journal synthesis for Dost / LevelLedger sessions. Use when the user asks to end the day, synthesize the session, write a journal, capture decision evolution, review open-type expectations and scenario prep quality, review how trades and reads developed, or preserve what was discussed with Dost for later review.
---

# Session Journal

Session Journal turns the current trading conversation into a durable decision record. It is not a live trading companion, scorekeeper, playbook updater, antipattern database, or Git workflow. Its job is to preserve how decisions evolved: what the user believed, what Dost argued, what evidence existed then, what the user did, and what can be learned later from both success and failure.

The user trades and thinks in New York time.

## Scope

- Write one journal entry for the trading date.
- Use the current chat context as the primary source.
- Pull LevelLedger / Skurry context only when it clarifies a key decision or disputed read.
- Include Dost's reasoning alongside the user's reasoning at key moments.
- Preserve uncertainty. Do not rewrite ambiguity as hindsight certainty.
- Review expectation-building quality explicitly: what open/day branches were prepared, what proof would have reduced them, and whether missing or wrong prep pulled the user into fast moves, repair assumptions, or insufficiently proven reversals.
- Skip screenshots, playbook updates, antipattern updates, scratchpad systems, and Git lifecycle.

## Output Paths

Stage locally first. Use the actual weekday name in the filename, not the literal word `Day`:

```text
C:\Heatmap\journal-out\YYYY\MM\YYYY-MM-DD-{Weekday}.md
```

Then export, with approval if required by the environment:

```text
W:\Skurry-Vault\Journals\YYYY\MM\YYYY-MM-DD-{Weekday}.md
```

After a successful export, verify the vault copy exists and then remove the staged local copy. The local staging file is a temporary export artifact, not a second archive. If `W:` is unavailable or approval is denied, leave the staged file in `C:\Heatmap\journal-out` and report that export is pending.

Note: in the default Codex sandbox, `W:` may appear missing even when the user's normal PowerShell can access it. The mapped drive lives outside the workspace sandbox and may not be mounted as a `PSDrive` inside the managed shell. Stage the journal locally first, then request elevated filesystem access for the final copy to `W:`, or tell the user to copy/export the staged file from their normal desktop shell.

## Workflow

### 1. Establish Date And Inputs

- Use today's New York trading date unless the user specifies another date.
- If the conversation spans multiple sessions or the date is unclear, ask one concise question before writing.
- Read recent journal examples from `W:\Skurry-Vault\Journals` only if the style is uncertain.
- Ask for a session rating only if the user has not already given one. If the user does not want to rate it, use `rating: null`.
- Choose session-specific tags from the discussion. Prefer news/event context (`fomc`, `cpi`, `ppi`, `nfp`), day type, auction regime, rollover/contract context, or the main decision theme. Do not add generic tags like `dost`, `levelledger`, or `nq` by default.

### 2. Build The Decision Timeline

Extract only moments that changed or tested the user's decision process:

- pre-open expectation setting, including which open/day scenarios were considered and which were missing,
- first-drive and first-return windows where a scenario's burden of proof should have been tested,
- entries, exits, adds, scratches, or deliberate no-trades,
- points where the user considered a trade and declined,
- moments where Dost challenged or refined the read,
- critical branch-reduction moments where one scenario gained/failed validity,
- shifts from probe to campaign, campaign to runner-only, or stand aside,
- emotional friction such as hope mode, FOMO, hesitation, revenge, over-fading, or over-aggression,
- genuinely ambiguous auction locations where neither the user nor Dost had a clean answer.

For each key moment, capture:

```markdown
### HH:MM - Area / Decision
**User read:** what the user believed or was considering.
**Dost audit:** what Dost argued or warned, if applicable.
**Evidence available then:** ownership, failures, references, context, and uncertainty known at the time.
**Scenario state:** which open/day branch was live, what proof it still needed, and what would have reduced or invalidated it.
**Decision:** what the user did or did not do.
**Outcome:** what happened next.
**Classification:** aligned execution / emotion-led action / hesitation / valid caution / evidence gap / ambiguous auction.
```

Do not force every moment into every field. Keep the entry readable.

### 3. Write The Journal

Use Obsidian-friendly Markdown with YAML frontmatter:

```markdown
---
date: 'YYYY-MM-DD'
day_type: [short label]
rating: [number or null]
tags:
- session-specific-tag
- another-specific-tag
type: journal
source: dost-session-journal
---

# YYYY-MM-DD - [Day Type]

> [!NOTE] One-sentence headline about the session's decision lesson.

---

## Session Arc

Chronological auction story focused on what mattered for decisions.

---

## Scenario Prep And Branch Reduction

Audit whether the user and Dost had the right conditional map before the auction
forced decisions. Keep this section honest about what was known in real time,
not what became easy after the day unfolded.

- **Pre-open branches:** open/day types or campaign paths that were considered.
- **Missing branch:** scenario that should have been loaded but was not, if any.
- **Burden of proof:** what each branch needed to prove around ETH/ON value,
  PM nodes, VWAP/open, prior value, IB, or major shelves.
- **Critical reductions:** moments where a branch should have been promoted,
  downgraded, or left unresolved.
- **Prep-quality effect:** whether expectation building helped navigation, or
  whether wrong/missing scenarios caused overcommitment to a fast move, an
  assumption that repair would sustain direction, or reversal hunting without
  sufficient counter-proof.
- **Reinforcement quality:** whether the day should reinforce prepared branch
  reduction, or whether PnL came mainly from smart local improvisation that
  should not become the primary process.

---

## Decision Timeline

Key moments using the structure above.

---

## Trades And Risk

Start with a compact table when trades or explicit no-trade decisions were discussed:

| Time | Action | Entry / Area | Size | Exit / Result | Thesis | Invalidation / Risk |
| --- | --- | --- | --- | --- | --- | --- |
| HH:MM | long / short / flat / no-trade | price or zone | size or unknown | price, result, or unknown | short reason | stop, structural failure, or unknown |

Then add brief prose covering entries, exits, scratches, adds, no-trades, and whether the risk/target logic was clear. Omit the table only when there was no concrete trade or no-trade decision to summarize.

---

## Process And Emotion

Where emotion helped, hurt, or stayed contained. Separate emotion from genuine auction complexity.

---

## Dost / User Read Alignment

Where Dost agreed, challenged, missed nuance, or helped reframe the user's read.

---

## Reflection

Non-punitive audit of what could have been clearer or better:

- whether pre-open or transition prep loaded the right scenarios,
- whether branch reduction happened early enough to preserve decision rhythm,
- what evidence would have improved the user's decision process,
- what Dost could have asked, flagged, or framed better,
- where the discussion had unresolved uncertainty or needed a cleaner evidence distinction,
- what should remain unresolved uncertainty rather than being converted into a lesson.

---

## Key Learning

One to three durable operating lessons from the session.

---

## Carry Forward

What to watch, review, or practice next session.
```

## Writing Rules

- Prefer decision-quality over completeness.
- Do not invent trades, prices, emotions, or motives. Mark unknowns plainly.
- Do not judge by P&L. Judge by quality of read, risk definition, execution, and adaptation.
- Separate professional process from outcome. A profitable improvisational day can be a weaker process day than a small-loss prepared day if the branch map was missing.
- Include successes and failures with the same tone.
- Keep Dost's arguments as arguments, not as authority. The goal is later review of the interaction, not proving who was right.
- Keep reflection non-punitive. Avoid loaded labels like `stupid`, `bad`, `weak`, or `obvious mistake` unless quoting the user is essential; translate them into neutral process language.
- If the user took no trades, still record the decision logic and no-trade discipline.
- If the day produced one important lesson, make the journal shorter and sharper rather than filling sections.

## Export

After writing the local staged journal, copy it to the vault path. Use a normal filesystem copy when possible:

```powershell
New-Item -ItemType Directory -Force -Path "W:\Skurry-Vault\Journals\YYYY\MM"
$staged = "C:\Heatmap\journal-out\YYYY\MM\YYYY-MM-DD-{Weekday}.md"
$exported = "W:\Skurry-Vault\Journals\YYYY\MM\YYYY-MM-DD-{Weekday}.md"
Copy-Item -LiteralPath $staged -Destination $exported -Force
if (Test-Path -LiteralPath $exported) {
    Remove-Item -LiteralPath $staged
} else {
    Write-Error "Export verification failed; staged journal left at $staged"
}
```

If the shell requires elevated access for `W:`, request approval for the copy. Do not silently skip export.
