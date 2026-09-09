# Root Risk Ownership Audit

Codex-authored research, 2026-09-09. This is a log reconstruction tool, not a
proposed trading engine or an implementation of anchor selection.

Findings and proposed changes:
[Root risk research](../KAHN_ROOT_RISK_RESEARCH_2026-09-09.md).

## Reproduce

Run from `C:\Heatmap` in PowerShell:

```powershell
& 'C:\Heatmap\skills\dost\.venv\Scripts\python.exe' -m unittest discover -s research/kahn/root_risk_study -p 'test_*.py' -v

& 'C:\Heatmap\skills\dost\.venv\Scripts\python.exe' research/kahn/root_risk_study/audit.py --log "$env:USERPROFILE\Documents\KahnRuntime\NQ\decisions.jsonl" --start '2026-09-04T13:30:00Z' --end '2026-09-09T15:03:00Z' --out research/out/kahn-root-risk-20260909
```

`audit.json` records the input prefix hash and line boundary, point-in-time
entry snapshots, and separately censored future outcome labels. The source
log is read-only. Output belongs under ignored `research/out/`.

## Interpretation Limits

- Start with the complete log, not a campaign-only excerpt. Existing live
  rails can precede campaign load. Older logs do not expose LL epoch UUIDs;
  the audit uses observed runtime/warmup boundaries as local generations.
- `directional_candidates` means previously owned, not subsequently failed,
  same-side rails wholly on the adverse side of the triggering band. This is
  an inventory diagnostic, NOT a causal association or entry qualification.
  `live_same_side` also retains overlapping/non-disjoint rails for inspection.
- A direct same-side OWN/HOLD entry already names a possible live owner. It
  does not need an additional directional candidate to pass this audit.
- `known_before_trigger_formed` and overlap pairs are diagnostics, not rules.
  A supply may form after a demand's birth but before that demand fails.
- The audit does not infer ownership from HOLD alone when earlier ownership
  records are absent, and does not treat TEST as FAIL.
- Future labels end at the next entry decision, campaign reload, LL warmup,
  runtime initialization, or the requested cutoff. They are not complete
  campaign P&L, and do not certify broker flatness.
- Rail outcome rows cover the trigger and pre-entry directional candidates.
  Later unrelated rail failures remain visible by identity in exit decisions;
  inspect the original log for those rails' full histories.
- Logged LL transitions are not a complete price tape. A failure's observed
  mid-price is not a broker stop price or a guaranteed executable fill.
- No production policy is simulated. No anchor is selected using later
  favorable movement, and no counterfactual execution P&L is claimed.
