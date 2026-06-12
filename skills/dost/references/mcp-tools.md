# MCP Tools

Dost uses two MCP servers when available.

## dost-levelledger

Purpose: LevelLedger ownership and L2 survival evidence.

Canonical launch from `C:\Heatmap\skills\dost`:

```powershell
uv run python -m dost.mcp_server
```

Configured transport: streamable-http at `http://127.0.0.1:8788/mcp`. Startup health is logged to stderr.

Tool:

- `ll_ownership_bands(date, symbol_dir="NQM6", window="09:30-10:30", warmup_min=90, topn=10, max_transitions=120)`

Use this for:

- durable demand/supply bands,
- failed tests,
- active ownership rails,
- contested failure clusters,
- capture span and data gaps.

Always read `data_health` before interpreting ownership. If the capture starts after the relevant event or has gaps inside the window, say so before making an auction claim.

## skurry-analyst

Purpose: traded context from tick data. Skurry does not know LevelLedger bands.

Existing launch from `D:\Apps\Skurry`:

```powershell
uv run python -m skurry.mcp_server
```

Configured transport: streamable-http at `http://127.0.0.1:8787/mcp` when started with Skurry's default `MCP_TRANSPORT`.

Useful tools for Dost:

- `market_session_refresh`: current bundle for live reads.
- `market_premarket`: ETH/pre-open positioning and overnight context.
- `market_context_snapshot`: daily/session context snapshot.
- `market_session_profile`: RTH/ETH profile structure.
- `market_profile`, `market_composite_profile`, `market_value_migration`: profile and multi-day context.
- `market_vwap`: VWAP context.
- `market_auction_quality`: auction quality from traded data.
- `market_candles`, `market_footprint`, `market_aggregate_footprint`: candle and footprint detail.
- `market_key_levels`, `market_single_prints`: structural references.

Use Skurry for profile shape, traded shelves, candles, VWAP, delta, and open/overnight context. Use LevelLedger for ownership survival. Do not let Skurry volume/profile output override LevelLedger durability.

## Evidence Order

For current-state questions:

1. Query `dost-levelledger` for the relevant window and inspect `data_health`.
2. Query `skurry-analyst` only for the traded context needed to frame the question.
3. Answer in Dost's normal format: `Read`, `Ownership`, `Evidence`, `Permission`, `What changes it`.

For morning map questions:

1. Query Skurry first for ETH/ON, profile, and prior context.
2. Query LevelLedger only if there is already live L2 capture for a pre-open/news leg that needs survival evidence.
3. State the auction contract: what must survive for upside/downside acceptance.
