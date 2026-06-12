---
name: session-journal
description: End-of-day trading journal synthesis for Dost / LevelLedger sessions. Use when the user asks to end the day, synthesize the session, write a journal, capture decision evolution, review how trades and reads developed, or preserve what was discussed with Dost for later review.
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
- Skip screenshots, playbook updates, antipattern updates, scratchpad systems, and Git lifecycle.

## Output Paths

Stage locally first:

```text
C:\Heatmap\journal-out\YYYY\MM\YYYY-MM-DD-Day.md
```

Then export, with approval if required by the environment:

```text
W:\Skurry-Vault\Journals\YYYY\MM\YYYY-MM-DD-Day.md
```

If `W:` is unavailable or approval is denied, leave the staged file in `C:\Heatmap\journal-out` and report that export is pending.

Note: in the default Codex sandbox, `W:` may appear missing even when the user's normal PowerShell can access it. The mapped drive lives outside the workspace sandbox and may not be mounted as a `PSDrive` inside the managed shell. Stage the journal locally first, then request elevated filesystem access for the final copy to `W:`, or tell the user to copy/export the staged file from their normal desktop shell.

## Workflow

### 1. Establish Date And Inputs

- Use today's New York trading date unless the user specifies another date.
- If the conversation spans multiple sessions or the date is unclear, ask one concise question before writing.
- Read recent journal examples from `W:\Skurry-Vault\Journals` only if the style is uncertain.
- Ask for a session rating only if the user has not already given one. If the user does not want to rate it, use `rating: null`.

### 2. Build The Decision Timeline

Extract only moments that changed or tested the user's decision process:

- entries, exits, adds, scratches, or deliberate no-trades,
- points where the user considered a trade and declined,
- moments where Dost challenged or refined the read,
- shifts from probe to campaign, campaign to runner-only, or stand aside,
- emotional friction such as hope mode, FOMO, hesitation, revenge, over-fading, or over-aggression,
- genuinely ambiguous auction locations where neither the user nor Dost had a clean answer.

For each key moment, capture:

```markdown
### HH:MM - Area / Decision
**User read:** what the user believed or was considering.
**Dost audit:** what Dost argued or warned, if applicable.
**Evidence available then:** ownership, failures, references, context, and uncertainty known at the time.
**Decision:** what the user did or did not do.
**Outcome:** what happened next.
**Classification:** clean execution / emotional override / hesitation / valid caution / skill gap / ambiguous auction.
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
- tag-one
- tag-two
type: journal
source: dost-session-journal
---

# YYYY-MM-DD - [Day Type]

> [!NOTE] One-sentence headline about the session's decision lesson.

---

## Session Arc

Chronological auction story focused on what mattered for decisions.

---

## Decision Timeline

Key moments using the structure above.

---

## Trades And Risk

Entries, exits, scratches, adds, no-trades, and whether the risk/target logic was clear.

---

## Process And Emotion

Where emotion helped, hurt, or stayed contained. Separate emotion from genuine auction complexity.

---

## Dost / User Read Alignment

Where Dost agreed, challenged, missed nuance, or helped reframe the user's read.

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
- Include successes and failures with the same tone.
- Keep Dost's arguments as arguments, not as authority. The goal is later review of the interaction, not proving who was right.
- If the user took no trades, still record the decision logic and no-trade discipline.
- If the day produced one important lesson, make the journal shorter and sharper rather than filling sections.

## Export

After writing the local staged journal, copy it to the vault path. Use a normal filesystem copy when possible:

```powershell
New-Item -ItemType Directory -Force -Path "W:\Skurry-Vault\Journals\YYYY\MM"
Copy-Item -LiteralPath "C:\Heatmap\journal-out\YYYY\MM\YYYY-MM-DD-Day.md" -Destination "W:\Skurry-Vault\Journals\YYYY\MM\YYYY-MM-DD-Day.md" -Force
```

If the shell requires elevated access for `W:`, request approval for the copy. Do not silently skip export.
