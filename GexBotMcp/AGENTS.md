# GexBotMcp

This folder is an exploratory MCP adapter for GexBot options-derived context.
It is not a Quantower runtime project and it must not become execution
authority.

## Invariants

- Keep credentials in local ignored files or environment variables only. The
  committed source must read `GEXBOT_API_KEY` but never embed a key.
- Prefer GexBot futures-aware tickers such as `ES_SPX` and `NQ_NDX` when Prep,
  Saavik, or Kahn need futures price-space context.
- Treat GEX, state greeks, and orderflow output as location, volatility, and
  path-stress context. They can shape Prep branches, Saavik checkpoint posture,
  or Kahn waypoint proposals, but they do not prove acceptance, sponsorship, or
  execution permission by themselves.
- Kahn may later consume this as normalized campaign context or proposed
  waypoints. Do not append raw GexBot levels to Kahn's evidence inbox as
  entry/add proof unless Kahn gets an explicit `GexBot` evidence source and a
  policy that keeps it non-permissive.
- Preserve raw API fields in tool responses so surprising schema changes are
  inspectable. Any normalized interpretation must be derived and labeled.

## MCP Shape

Default transport is streamable-http at `http://127.0.0.1:8789/mcp`.

Canonical launch from `C:\Heatmap\GexBotMcp`:

```powershell
uv run python -m gexbot_mcp.mcp_server
```

The intended first consumer is conversation-time Prep/Saavik. Kahn integration
should start with offline replay experiments that convert GexBot context into
campaign waypoints or non-permissive context markers before any live runtime
policy changes.
