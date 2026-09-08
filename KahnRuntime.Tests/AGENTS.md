# Kahn Runtime Offline Tests

- Link pure sources only, not the deploying KahnRuntime project. This executable
  has no Quantower reference, gateway, live file controls, or broker connection.
- Preserve existing RuntimeSelfTests as legacy regression coverage. Session tests
  exercise the pure coordinator used by the worker; they do not simulate a broker
  by treating accepted submissions as fills.
- Synthetic tests assert mechanisms, including failures and vetoes. Replay
  comparisons must retain failed roots and report changed permissions honestly.
- Captured sample identity comes from the local engine's export contract; never
  generalize timestamp grouping to arbitrary external JSONL evidence.
- Build output stays in this project. Replay output belongs under research/out
  in a new directory, never overwrite frozen prior-study output.
- Python writable profiles stay under `.tmp/kahn-transport-tests`: Windows Python
  private temporary-directory ACLs can prevent the sandbox from reading them.
- First-dispatch coverage must consume the actual C# checkpoint writer's disk
  output, not only hand-built Python checkpoints or in-memory C# defaults.
