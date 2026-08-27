# GexBot MCP Prototype

Exploratory MCP adapter for GexBot options context, with a local SQLite cache for
intraday wall history.

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
`gex_full` calls worked for `ES_SPX` and `NQ_NDX`. `state`, `orderflow`,
`research`, and historical `/hist/...` calls returned HTTP 403 with the current
key, so live Classic chain snapshots are the usable source for now.

## Run

Run one module during the session:

```powershell
cd GexBotMcp
uv run python -m gexbot_mcp.mcp_server
```

Default MCP URL: `http://127.0.0.1:8789/mcp`.

The MCP server opens a WAL SQLite cache at `GexBotMcp/out/gexbot.sqlite`, starts
a background poller, and stores raw plus normalized Classic chain snapshots.
`GexBotMcp/out/` is ignored. The default poller watches `ES_SPX,NQ_NDX` across
`gex_zero,gex_full,gex_one`, polls every 60 seconds, keeps 30 days, and only
auto-polls from 09:30 to 16:00 New York time because off-hours API responses are
just the prior close snapshot.

The standalone script remains only as a debug wrapper over the same SQLite cache:

```powershell
uv run python GexBotMcp\scripts\record_gexbot.py --once --tickers ES_SPX --categories gex_zero
```

## Configuration

Environment overrides:

- `GEXBOT_CACHE_PATH`: SQLite path, default `GexBotMcp/out/gexbot.sqlite`.
- `GEXBOT_CACHE_TTL_DAYS`: retention, default `30`.
- `GEXBOT_POLL_ENABLED`: background poller, default `true`.
- `GEXBOT_POLL_RTH_ONLY`: restrict auto-polling to NY RTH, default `true`.
- `GEXBOT_POLL_START_NY` / `GEXBOT_POLL_END_NY`: default `09:30` / `16:00`.
- `GEXBOT_POLL_TICKERS`: comma-separated tickers, default `ES_SPX,NQ_NDX`.
- `GEXBOT_POLL_CATEGORIES`: comma-separated categories, default
  `gex_zero,gex_full,gex_one`.
- `GEXBOT_POLL_INTERVAL_SEC`: default `60`.
- `GEXBOT_MAX_AGE_SEC`: max cached age before refresh-on-demand, default `60`.

## Tool Contract

- `gexbot_health(network_check=False)`: reports key/config, cache, poller, and
  optional ticker probe status.
- `gexbot_cache_status()`: reports SQLite row counts and cached groups.
- `gexbot_tickers()`: lists supported public ticker groups.
- `gexbot_categories(package)`: lists API category names for `classic`, `state`,
  or `orderflow`.
- `gexbot_refresh(tickers="", categories="")`: manually forces one cache poll;
  this intentionally bypasses the automatic RTH pause.
- `gexbot_snapshot(..., view="chain", max_age_sec=None, force_refresh=False)`:
  returns raw chain data through the cache. Non-chain views are live uncached.
- `gexbot_decision_context(..., max_age_sec=None, force_refresh=False)`: returns
  normalized context from cache or live refresh. Responses include `cache.source`
  as `live_refresh`, `cache_hit`, `stale_cache_fallback`, or
  `outside_poll_window_cache`.
- `gexbot_wall_history(ticker="ES_SPX", category="gex_zero", since=None,
  until=None, session_date=None, since_minutes=None, limit=500, refresh=True,
  force_refresh=False)`: returns cached wall rows and detected wall changes.
  `since="09:30"` is interpreted as New York time for `session_date` or today.

## Decision Boundary

GexBot context can help answer: where are option dealers likely to pin, defend,
accelerate, or force stress? It cannot answer: did RTH accept, who owns the
auction, is the current entry proven, or should Kahn add.

For Kahn, the safe first use is to turn GexBot levels into proposed campaign
waypoints:

- zero gamma: `evaluate` or `path_stress` boundary,
- `call_wall` is the Classic volume-derived major positive GEX level
  (`major_pos_vol`),
- `put_wall` is the Classic volume-derived major negative GEX level
  (`major_neg_vol`),
- OI-derived variants are preserved as `oi_call_wall` and `oi_put_wall`,
- `maxchange`/`max_priors` describes recent GEX change by lookback and should
  not be treated as the static wall,
- wall removals/relocations are context-change triggers for Saavik/Kahn
  checkpoint review, not execution permission by themselves,
- large nearby strike profile: watch zone for effort/no-reward or volatility
  compression.

Kahn should still require LevelLedger, BubbleTape, footprint, price acceptance,
or explicit user campaign input for execution-affecting decisions.
