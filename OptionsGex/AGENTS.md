# OptionsGex

This folder is an after-close research feature, not a Quantower runtime
project. It converts a user-downloaded Cboe SPX `quotedata.csv` into a concise
ES options-location map that Prep can generate and read the next morning.

## Invariants

- Do not automate Cboe delayed-quote extraction. The input CSV is manually
  downloaded by the user.
- Keep source data local and ignored. Default input is
  `OptionsGex/input/spx_quotedata.csv`; generated maps go under
  `OptionsGex/out/`.
- Recompute the SPX-to-ES basis every run from synchronized references, usually
  SPX close from the CSV and ES RTH close from Skurry/Quantower. Do not hard-code
  yesterday's basis.
- Default next-session map excludes expired same-day contracts and uses 1-5
  calendar DTE.
- Cboe chain columns are positional because the header repeats names:
  call gamma/OI are columns 9/10, put gamma/OI are columns 20/21. Validate this
  before changing parser logic.
- Treat GEX rows as location, magnet, pin, or acceleration context only. They do
  not replace Skurry profile evidence, acceptance/rejection, or Prep falsifiers.

## Output Contract

`OptionsGex/out/latest.md` is the stable handoff for Prep after it runs the
script with a Skurry-derived ES reference. Timestamped Markdown files in the
same folder preserve each run. Do not commit CSV inputs or generated maps unless
the user explicitly asks for a dated research artifact.
