# OptionsGex

This folder is an after-close research feature, not a Quantower runtime
project. It converts user-downloaded Cboe SPX/NDX `quotedata.csv` files into
concise ES/NQ options-location maps that Prep can generate and read the next
morning.

## Invariants

- Do not automate Cboe delayed-quote extraction. The input CSV is manually
  downloaded by the user.
- Keep source data local and ignored. Default inputs are
  `OptionsGex/input/spx_quotedata.csv` and
  `OptionsGex/input/ndx_quotedata.csv`; generated maps go under
  `OptionsGex/out/`.
- Recompute each futures-index basis every run from synchronized references,
  usually index close from the CSV and ES/NQ RTH close from Skurry/Quantower.
  Do not hard-code yesterday's basis.
- Default next-session map excludes expired same-day contracts and uses 1-5
  calendar DTE.
- Cboe chain columns are positional because the header repeats names:
  call gamma/OI are columns 9/10, put gamma/OI are columns 20/21. Validate this
  before changing parser logic.
- Treat GEX rows as location, magnet, pin, or acceleration context only. They do
  not replace Skurry profile evidence, acceptance/rejection, or Prep falsifiers.

## Output Contract

`OptionsGex/out/latest-spx-es.md` and `OptionsGex/out/latest-ndx-nq.md` are the
stable per-product handoffs for Prep after it runs the script with
Skurry-derived futures references. `OptionsGex/out/latest.md` remains the
combined latest handoff for whichever product set was just generated.
Timestamped Markdown files in the same folder preserve each run. Do not commit
CSV inputs or generated maps unless the user explicitly asks for a dated
research artifact.
