from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gexbot_mcp.cache import GexBotCache  # noqa: E402
from gexbot_mcp.client import GexBotApiError  # noqa: E402
from gexbot_mcp.context import build_decision_context  # noqa: E402
from gexbot_mcp.service import GexBotServiceConfig, GexBotSnapshotService  # noqa: E402


SAMPLE = {
    "timestamp": 1777492800,
    "ticker": "ES_SPX",
    "min_dte": 0,
    "sec_min_dte": 1,
    "spot": 7138.55,
    "zero_gamma": 7112.95,
    "major_pos_vol": 7135,
    "major_pos_oi": 7200,
    "major_neg_vol": 7100,
    "major_neg_oi": 6900,
    "strikes": [
        [6890, -228.01, -86.9, [-240.55]],
        [7135, 1145886.722, 997473.336, [0]],
        [7140, 170979.742, 51521.105, [0]],
        [7200, 88.2, 400000.0, [0]],
    ],
    "sum_gex_vol": 1712585.519,
    "sum_gex_oi": 51521.105,
    "delta_risk_reversal": 0.118,
}


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    def chart(self, *, ticker: str, package: str, category: str) -> dict:
        self.calls += 1
        if self.fail:
            raise GexBotApiError("forced failure", status=503)
        payload = dict(SAMPLE)
        payload["ticker"] = ticker.upper()
        return payload

    def health(self, *, network_check: bool = False) -> dict:
        return {"ok": True, "network_check": network_check}


class CacheServiceTests(unittest.TestCase):
    def test_cache_stores_latest_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = GexBotCache(Path(tmp) / "gexbot.sqlite", ttl_days=30)
            context = build_decision_context(SAMPLE, package="classic", category="gex_zero")
            record = cache.store_success(
                ticker="ES_SPX",
                package="classic",
                category="gex_zero",
                payload=SAMPLE,
                context=context,
                recorded_at_utc="2026-04-29T20:00:01Z",
            )

            latest = cache.latest(ticker="ES_SPX", package="classic", category="gex_zero")
            history = cache.history(ticker="ES_SPX", package="classic", category="gex_zero")

            self.assertEqual(record.call_wall, 7135.0)
            self.assertIsNotNone(latest)
            self.assertEqual(latest.put_wall, 7100.0)
            self.assertEqual([item.row_id for item in history], [record.row_id])
            self.assertEqual(cache.stats()["rows"], 1)
            cache.close()

    def test_service_refreshes_hits_cache_and_falls_back_to_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            cache = GexBotCache(Path(tmp) / "gexbot.sqlite", ttl_days=30)
            config = GexBotServiceConfig(
                cache_path=Path(tmp) / "gexbot.sqlite",
                poll_enabled=False,
                poll_market_hours_only=False,
                max_age_sec=60,
            )
            service = GexBotSnapshotService(config=config, client=client, cache=cache)
            try:
                first = service.decision_context(ticker="ES_SPX", package="classic", category="gex_zero")
                second = service.decision_context(ticker="ES_SPX", package="classic", category="gex_zero")
                client.fail = True
                fallback = service.decision_context(
                    ticker="ES_SPX",
                    package="classic",
                    category="gex_zero",
                    force_refresh=True,
                )
                history = service.wall_history(ticker="ES_SPX", package="classic", category="gex_zero")

                self.assertEqual(first["cache"]["source"], "live_refresh")
                self.assertEqual(second["cache"]["source"], "cache_hit")
                self.assertEqual(fallback["cache"]["source"], "stale_cache_fallback")
                self.assertEqual(fallback["cache"]["live_error"], "forced failure")
                self.assertEqual(client.calls, 2)
                self.assertEqual(history["count"], 1)
                self.assertEqual(history["rows"][0]["call_wall"], 7135.0)
            finally:
                cache.close()

    def test_poll_window_status_uses_new_york_rth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = GexBotCache(Path(tmp) / "gexbot.sqlite", ttl_days=30)
            config = GexBotServiceConfig(
                cache_path=Path(tmp) / "gexbot.sqlite",
                poll_enabled=False,
                poll_market_hours_only=True,
            )
            service = GexBotSnapshotService(config=config, client=FakeClient(), cache=cache)
            try:
                open_status = service.poll_window_status(now=datetime(2026, 8, 26, 14, 0, tzinfo=timezone.utc))
                after_status = service.poll_window_status(now=datetime(2026, 8, 26, 21, 0, tzinfo=timezone.utc))

                self.assertTrue(open_status["is_open"])
                self.assertEqual(open_status["state"], "open")
                self.assertFalse(after_status["is_open"])
                self.assertEqual(after_status["state"], "after_close")
            finally:
                cache.close()

    def test_prune_removes_rows_older_than_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = GexBotCache(Path(tmp) / "gexbot.sqlite", ttl_days=30)
            context = build_decision_context(SAMPLE, package="classic", category="gex_zero")
            old_time = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat().replace("+00:00", "Z")
            cache.store_success(
                ticker="ES_SPX",
                package="classic",
                category="gex_zero",
                payload=SAMPLE,
                context=context,
                recorded_at_utc=old_time,
            )

            self.assertEqual(cache.prune(ttl_days=30), 1)
            self.assertEqual(cache.stats()["rows"], 0)
            cache.close()


if __name__ == "__main__":
    unittest.main()
