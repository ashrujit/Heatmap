# GexBot MCP Prototype

Exploratory MCP adapter for GexBot options context.

## Setup

The local key is stored in ignored `GexBotMcp/.env`. You can also provide it as
`GEXBOT_API_KEY` in the process environment.

Run local verification:

```powershell
python -m unittest discover GexBotMcp\tests
python -m compileall GexBotMcp\src GexBotMcp\scripts GexBotMcp\tests
```

Run a live smoke check:

```powershell
python GexBotMcp\scripts\smoke_gexbot.py decision-context --ticker ES_SPX --package classic --category gex_full --center-price 7700 --radius-points 80
```

Observed on 2026-08-26: the stored key loaded successfully, public tickers
returned 54 stocks, 4 indexes, and 2 futures, and authenticated `classic`
`gex_full` calls worked for `ES_SPX` and `NQ_NDX`. `state` and `orderflow`
calls returned HTTP 403 with the current key, so treat those surfaces as
implemented but not currently licensed.

Run the MCP server:

```powershell
cd GexBotMcp
uv run python -m gexbot_mcp.mcp_server
```

Default MCP URL: `http://127.0.0.1:8789/mcp`.

## Tool Contract

- `gexbot_health(network_check=False)`: reports key/config status and can do a
  public ticker probe.
- `gexbot_tickers()`: lists supported public tickers.
- `gexbot_categories(package)`: lists API category names for `classic`, `state`,
  or `orderflow`.
- `gexbot_snapshot(ticker, package="classic", category="gex_full",
  view="chain")`: fetches raw chain, majors, max-change, or orderflow data.
- `gexbot_decision_context(...)`: fetches chain data and returns normalized
  levels, nearby strikes, regime hint, and explicit Prep/Saavik/Kahn usage
  boundaries.

## Decision Boundary

GexBot context can help answer: where are option dealers likely to pin, defend,
accelerate, or force stress? It cannot answer: did RTH accept, who owns the
auction, is the current entry proven, or should Kahn add.

For Kahn, the safe first use is to turn GexBot levels into proposed campaign
waypoints:

- zero gamma: `evaluate` or `path_stress` boundary,
- positive GEX / call-wall style levels: target, no-add, or resistance context,
- negative GEX / put-wall style levels: target, no-add, or support context,
- large nearby strike profile: watch zone for effort/no-reward or volatility
  compression.

Kahn should still require LevelLedger, BubbleTape, footprint, price acceptance,
or explicit user campaign input for execution-affecting decisions.
