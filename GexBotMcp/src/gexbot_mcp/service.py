"""Refresh and cache service for GexBot MCP tools."""

from __future__ import annotations

import atexit
import logging
import os
import re
import threading
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .cache import DEFAULT_CACHE_PATH, GexBotCache, SnapshotRecord, parse_utc, utc_now_iso
from .client import GexBotApiError, GexBotClient
from .context import build_decision_context, snapshot_summary


DEFAULT_TICKERS = ("ES_SPX", "NQ_NDX")
DEFAULT_CATEGORIES = ("gex_zero", "gex_full", "gex_one")

try:
    NY = ZoneInfo("America/New_York")
except Exception:  # Windows stdlib lacks IANA data unless tzdata is installed.
    NY = datetime.now().astimezone().tzinfo or timezone(timedelta(hours=-4), "America/New_York")
logger = logging.getLogger("gexbot_mcp.service")


@dataclass(frozen=True)
class GexBotServiceConfig:
    cache_path: Path = DEFAULT_CACHE_PATH
    ttl_days: int = 30
    poll_enabled: bool = True
    poll_market_hours_only: bool = True
    poll_start_ny: str = "09:30"
    poll_end_ny: str = "16:00"
    poll_tickers: tuple[str, ...] = DEFAULT_TICKERS
    poll_categories: tuple[str, ...] = DEFAULT_CATEGORIES
    poll_interval_sec: float = 60.0
    max_age_sec: float = 60.0
    tick_size: float = 0.25
    zone_ticks: int = 8
    max_strikes: int = 40

    @classmethod
    def from_env(cls) -> "GexBotServiceConfig":
        return cls(
            cache_path=Path(os.getenv("GEXBOT_CACHE_PATH", str(DEFAULT_CACHE_PATH))),
            ttl_days=_int_env("GEXBOT_CACHE_TTL_DAYS", 30, minimum=1),
            poll_enabled=_bool_env("GEXBOT_POLL_ENABLED", True),
            poll_market_hours_only=_bool_env("GEXBOT_POLL_RTH_ONLY", True),
            poll_start_ny=os.getenv("GEXBOT_POLL_START_NY", "09:30").strip() or "09:30",
            poll_end_ny=os.getenv("GEXBOT_POLL_END_NY", "16:00").strip() or "16:00",
            poll_tickers=tuple(_split_csv(os.getenv("GEXBOT_POLL_TICKERS", ",".join(DEFAULT_TICKERS)))),
            poll_categories=tuple(_split_csv(os.getenv("GEXBOT_POLL_CATEGORIES", ",".join(DEFAULT_CATEGORIES)))),
            poll_interval_sec=_float_env("GEXBOT_POLL_INTERVAL_SEC", 60.0, minimum=5.0),
            max_age_sec=_float_env("GEXBOT_MAX_AGE_SEC", 60.0, minimum=0.0),
            tick_size=_float_env("GEXBOT_TICK_SIZE", 0.25, minimum=0.000001),
            zone_ticks=_int_env("GEXBOT_ZONE_TICKS", 8, minimum=0),
            max_strikes=_int_env("GEXBOT_MAX_STRIKES", 40, minimum=0),
        )


class GexBotSnapshotService:
    def __init__(
        self,
        *,
        config: GexBotServiceConfig | None = None,
        client: GexBotClient | None = None,
        cache: GexBotCache | None = None,
    ) -> None:
        self.config = config or GexBotServiceConfig.from_env()
        self.client = client or GexBotClient()
        self.cache = cache or GexBotCache(self.config.cache_path, ttl_days=self.config.ttl_days)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_prune_at: datetime | None = None
        atexit.register(self.stop_background_poller)

    def health(self, *, network_check: bool = False) -> dict[str, Any]:
        result = self.client.health(network_check=network_check)
        result["cache"] = self.cache.stats()
        result["poller"] = {
            "enabled": self.config.poll_enabled,
            "running": self._thread is not None and self._thread.is_alive(),
            "tickers": list(self.config.poll_tickers),
            "categories": list(self.config.poll_categories),
            "interval_sec": self.config.poll_interval_sec,
            "max_age_sec": self.config.max_age_sec,
            "market_hours_only": self.config.poll_market_hours_only,
            "poll_start_ny": self.config.poll_start_ny,
            "poll_end_ny": self.config.poll_end_ny,
            "window": self.poll_window_status(),
        }
        return result

    def poll_window_status(self, *, now: datetime | None = None) -> dict[str, Any]:
        now_utc = now.astimezone(timezone.utc) if now is not None else datetime.now(timezone.utc)
        now_ny = now_utc.astimezone(NY)
        start = _time_on_date(now_ny.date(), self.config.poll_start_ny)
        end = _time_on_date(now_ny.date(), self.config.poll_end_ny)
        if end <= start:
            end += timedelta(days=1)
        is_open = start <= now_ny < end
        next_start = start if now_ny < start else start + timedelta(days=1)
        if is_open:
            state = "open"
            seconds_until_open = 0.0
            seconds_until_close = max(0.0, (end - now_ny).total_seconds())
        elif now_ny < start:
            state = "before_open"
            seconds_until_open = max(0.0, (start - now_ny).total_seconds())
            seconds_until_close = None
        else:
            state = "after_close"
            seconds_until_open = max(0.0, (next_start - now_ny).total_seconds())
            seconds_until_close = None
        return {
            "state": state,
            "is_open": is_open,
            "now_ny": now_ny.isoformat(),
            "start_ny": start.isoformat(),
            "end_ny": end.isoformat(),
            "next_start_ny": next_start.isoformat(),
            "seconds_until_open": seconds_until_open,
            "seconds_until_close": seconds_until_close,
        }

    def start_background_poller(self) -> bool:
        if not self.config.poll_enabled:
            logger.info("CACHE: GexBot background polling disabled")
            return False
        if self._thread is not None and self._thread.is_alive():
            return True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._poll_loop, name="GexBotPoller", daemon=True)
        self._thread.start()
        logger.info(
            "CACHE: GexBot poller started tickers=%s categories=%s interval_sec=%s rth_only=%s db=%s",
            ",".join(self.config.poll_tickers),
            ",".join(self.config.poll_categories),
            self.config.poll_interval_sec,
            self.config.poll_market_hours_only,
            self.cache.path,
        )
        return True

    def stop_background_poller(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def poll_once(
        self,
        *,
        tickers: tuple[str, ...] | None = None,
        categories: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        self._prune_if_needed()
        results: list[dict[str, Any]] = []
        for ticker in tickers or self.config.poll_tickers:
            for category in categories or self.config.poll_categories:
                result = self.refresh_chain(
                    ticker=ticker,
                    package="classic",
                    category=category,
                    tick_size=self.config.tick_size,
                    zone_ticks=self.config.zone_ticks,
                    max_strikes=self.config.max_strikes,
                )
                results.append(result)
                logger.info(format_poll_result(result))
        return results

    def refresh_chain(
        self,
        *,
        ticker: str,
        package: str,
        category: str,
        tick_size: float | None = None,
        zone_ticks: int | None = None,
        max_strikes: int | None = None,
    ) -> dict[str, Any]:
        recorded_at = utc_now_iso()
        tick_size = self.config.tick_size if tick_size is None else tick_size
        zone_ticks = self.config.zone_ticks if zone_ticks is None else zone_ticks
        max_strikes = self.config.max_strikes if max_strikes is None else max_strikes
        try:
            payload = self.client.chart(ticker=ticker, package=package, category=category)
            context = build_decision_context(
                payload,
                package=package,
                category=category,
                max_strikes=max_strikes,
                tick_size=tick_size,
                zone_ticks=zone_ticks,
            )
            record = self.cache.store_success(
                ticker=ticker,
                package=package,
                category=category,
                payload=payload,
                context=context,
                recorded_at_utc=recorded_at,
            )
            return {"ok": True, "source": "live_refresh", "record": record.to_dict(include_raw=False)}
        except (GexBotApiError, ValueError) as exc:
            record = self.cache.store_error(
                ticker=ticker,
                package=package,
                category=category,
                error=str(exc),
                status=getattr(exc, "status", None),
                recorded_at_utc=recorded_at,
            )
            return {"ok": False, "source": "live_refresh_error", "error": str(exc), "record": record.to_dict()}

    def decision_context(
        self,
        *,
        ticker: str,
        package: str,
        category: str,
        center_price: float | None = None,
        radius_points: float | None = None,
        max_strikes: int | None = None,
        tick_size: float | None = None,
        zone_ticks: int | None = None,
        max_age_sec: float | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        max_age = self.config.max_age_sec if max_age_sec is None else max(0.0, float(max_age_sec))
        latest = self.cache.latest(ticker=ticker, package=package, category=category, ok_only=True)
        age = latest.age_seconds() if latest is not None else None
        outside_poll_window = self.config.poll_market_hours_only and not self.poll_window_status()["is_open"]
        if latest is not None and not force_refresh and outside_poll_window:
            return self._context_from_record(
                latest,
                source="outside_poll_window_cache",
                package=package,
                category=category,
                center_price=center_price,
                radius_points=radius_points,
                max_strikes=max_strikes,
                tick_size=tick_size,
                zone_ticks=zone_ticks,
            )
        if latest is not None and not force_refresh and age is not None and age <= max_age:
            return self._context_from_record(
                latest,
                source="cache_hit",
                package=package,
                category=category,
                center_price=center_price,
                radius_points=radius_points,
                max_strikes=max_strikes,
                tick_size=tick_size,
                zone_ticks=zone_ticks,
            )

        refresh = self.refresh_chain(
            ticker=ticker,
            package=package,
            category=category,
            tick_size=tick_size,
            zone_ticks=zone_ticks,
            max_strikes=max_strikes,
        )
        if refresh.get("ok"):
            refreshed = self.cache.latest(ticker=ticker, package=package, category=category, ok_only=True)
            if refreshed is not None:
                return self._context_from_record(
                    refreshed,
                    source="live_refresh",
                    package=package,
                    category=category,
                    center_price=center_price,
                    radius_points=radius_points,
                    max_strikes=max_strikes,
                    tick_size=tick_size,
                    zone_ticks=zone_ticks,
                )

        if latest is not None:
            return self._context_from_record(
                latest,
                source="stale_cache_fallback",
                package=package,
                category=category,
                center_price=center_price,
                radius_points=radius_points,
                max_strikes=max_strikes,
                tick_size=tick_size,
                zone_ticks=zone_ticks,
                live_error=refresh.get("error"),
            )

        return {
            "ok": False,
            "ticker": ticker.upper(),
            "package": package,
            "category": category,
            "error": refresh.get("error") or "no cached GexBot snapshot and live refresh failed",
            "cache": {"source": "live_refresh_error", "db_path": str(self.cache.path)},
        }

    def snapshot(
        self,
        *,
        ticker: str,
        package: str,
        category: str,
        view: str,
        max_age_sec: float | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        if view.lower().strip() != "chain":
            payload = _live_snapshot(self.client, ticker=ticker, package=package, category=category, view=view)
            return {
                "ok": True,
                "ticker": ticker.upper(),
                "package": package,
                "category": category,
                "view": view,
                "summary": snapshot_summary(payload),
                "cache": {"source": "live_uncached", "reason": "only chain snapshots are cached"},
                "raw": payload,
            }

        context = self.decision_context(
            ticker=ticker,
            package=package,
            category=category,
            max_age_sec=max_age_sec,
            force_refresh=force_refresh,
        )
        if not context.get("ok"):
            return context
        latest = self.cache.latest(ticker=ticker, package=package, category=category, ok_only=True)
        payload = latest.raw if latest is not None else None
        return {
            "ok": True,
            "ticker": ticker.upper(),
            "package": package,
            "category": category,
            "view": view,
            "summary": snapshot_summary(payload),
            "cache": context.get("cache"),
            "raw": payload,
        }

    def wall_history(
        self,
        *,
        ticker: str,
        package: str,
        category: str,
        since: str | None = None,
        until: str | None = None,
        session_date: str | None = None,
        since_minutes: float | None = None,
        limit: int = 500,
        refresh: bool = True,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        if refresh:
            self.decision_context(
                ticker=ticker,
                package=package,
                category=category,
                max_age_sec=self.config.max_age_sec,
                force_refresh=force_refresh,
            )
        now = datetime.now(timezone.utc)
        since_utc = None
        if since_minutes is not None and since_minutes > 0:
            since_utc = (now - timedelta(minutes=since_minutes)).isoformat().replace("+00:00", "Z")
        elif since:
            since_utc = _parse_time_filter(since, session_date=session_date)
        until_utc = _parse_time_filter(until, session_date=session_date) if until else None
        rows = self.cache.history(
            ticker=ticker,
            package=package,
            category=category,
            since_utc=since_utc,
            until_utc=until_utc,
            limit=limit,
            ok_only=True,
        )
        items = [_wall_item(row) for row in rows]
        return {
            "ok": True,
            "ticker": ticker.upper(),
            "package": package,
            "category": category,
            "cache": {"db_path": str(self.cache.path), "ttl_days": self.cache.ttl_days},
            "query": {
                "since_utc": since_utc,
                "until_utc": until_utc,
                "session_date": session_date,
                "since_minutes": since_minutes,
                "limit": limit,
                "refresh": refresh,
                "force_refresh": force_refresh,
            },
            "count": len(items),
            "wall_changes": _wall_changes(items),
            "rows": items,
        }

    def cache_status(self) -> dict[str, Any]:
        return {"ok": True, "cache": self.cache.stats(), "poll_window": self.poll_window_status()}

    def with_config(self, **kwargs: Any) -> "GexBotSnapshotService":
        return GexBotSnapshotService(config=replace(self.config, **kwargs), client=self.client, cache=self.cache)

    def _context_from_record(
        self,
        record: SnapshotRecord,
        *,
        source: str,
        package: str,
        category: str,
        center_price: float | None,
        radius_points: float | None,
        max_strikes: int | None,
        tick_size: float | None,
        zone_ticks: int | None,
        live_error: str | None = None,
    ) -> dict[str, Any]:
        payload = record.raw if isinstance(record.raw, dict) else {}
        context = build_decision_context(
            payload,
            package=package,
            category=category,
            center_price=center_price,
            radius_points=radius_points,
            max_strikes=self.config.max_strikes if max_strikes is None else max_strikes,
            tick_size=self.config.tick_size if tick_size is None else tick_size,
            zone_ticks=self.config.zone_ticks if zone_ticks is None else zone_ticks,
        )
        context["cache"] = {
            "source": source,
            "db_path": str(self.cache.path),
            "record_id": record.row_id,
            "recorded_at_utc": record.recorded_at_utc,
            "api_as_of_utc": record.api_as_of_utc,
            "cache_age_sec": record.age_seconds(),
            "ttl_days": self.cache.ttl_days,
            "outside_poll_window": source == "outside_poll_window_cache",
            "live_error": live_error,
        }
        return context

    def _poll_loop(self) -> None:
        last_closed_state: str | None = None
        while not self._stop_event.is_set():
            if self.config.poll_market_hours_only:
                window = self.poll_window_status()
                if not window["is_open"]:
                    if window["state"] != last_closed_state:
                        logger.info(
                            "CACHE: GexBot poller sleeping state=%s next_start_ny=%s",
                            window["state"],
                            window["next_start_ny"],
                        )
                        last_closed_state = window["state"]
                    wait = min(300.0, max(5.0, float(window["seconds_until_open"] or 60.0)))
                    if self._stop_event.wait(wait):
                        break
                    continue
                last_closed_state = None
            try:
                self.poll_once()
            except Exception as exc:  # pragma: no cover - long-running live guard
                logger.exception("ERR: GexBot poller failed: %s", exc)
            if self._stop_event.wait(self.config.poll_interval_sec):
                break

    def _prune_if_needed(self) -> None:
        now = datetime.now(timezone.utc)
        if self._last_prune_at is not None and (now - self._last_prune_at).total_seconds() < 3600:
            return
        removed = self.cache.prune()
        self._last_prune_at = now
        if removed:
            logger.info("CACHE: pruned %s GexBot rows older than %s days", removed, self.cache.ttl_days)


def format_poll_result(result: dict[str, Any]) -> str:
    record = result.get("record") or {}
    if not result.get("ok"):
        return f"ERR: GEX {record.get('ticker', 'NA')} {record.get('category', 'NA')} {result.get('error', 'unknown error')}"
    return (
        f"GEX: {record.get('ticker')} {record.get('category')} "
        f"api_ts={record.get('api_as_of_utc')} spot={_price(record.get('spot'))} "
        f"call={_price(record.get('call_wall'))} put={_price(record.get('put_wall'))} "
        f"oi_call={_price(record.get('oi_call_wall'))} oi_put={_price(record.get('oi_put_wall'))} "
        f"sum_vol={_number_text(record.get('sum_gex_vol'))} sum_oi={_number_text(record.get('sum_gex_oi'))} "
        f"recorded={record.get('recorded_at_utc')}"
    )


def _live_snapshot(client: GexBotClient, *, ticker: str, package: str, category: str, view: str) -> dict[str, Any]:
    normalized_view = view.lower().strip()
    if normalized_view == "chain":
        return client.chart(ticker=ticker, package=package, category=category)
    if normalized_view == "majors":
        return client.majors(ticker=ticker, package=package, category=category)
    if normalized_view == "maxchange":
        return client.maxchange(ticker=ticker, package=package, category=category)
    if normalized_view == "orderflow":
        return client.orderflow(ticker=ticker)
    raise ValueError("view must be one of chain, majors, maxchange, orderflow")


def _wall_item(record: SnapshotRecord) -> dict[str, Any]:
    return {
        "id": record.row_id,
        "recorded_at_utc": record.recorded_at_utc,
        "api_as_of_utc": record.api_as_of_utc,
        "spot": record.spot,
        "zero_gamma": record.zero_gamma,
        "call_wall": record.call_wall,
        "put_wall": record.put_wall,
        "oi_call_wall": record.oi_call_wall,
        "oi_put_wall": record.oi_put_wall,
        "sum_gex_vol": record.sum_gex_vol,
        "sum_gex_oi": record.sum_gex_oi,
    }


def _wall_changes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = ("zero_gamma", "call_wall", "put_wall", "oi_call_wall", "oi_put_wall", "sum_gex_vol", "sum_gex_oi")
    changes: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    for row in rows:
        if previous is None:
            previous = row
            continue
        changed = {}
        for field in fields:
            if row.get(field) != previous.get(field):
                changed[field] = {"from": previous.get(field), "to": row.get(field)}
        if changed:
            changes.append(
                {
                    "recorded_at_utc": row.get("recorded_at_utc"),
                    "api_as_of_utc": row.get("api_as_of_utc"),
                    "changes": changed,
                }
            )
        previous = row
    return changes


def _parse_time_filter(value: str, *, session_date: str | None) -> str:
    raw = value.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", raw):
        date_text = session_date or datetime.now(NY).date().isoformat()
        dt = datetime.fromisoformat(f"{date_text}T{raw}")
        return dt.replace(tzinfo=NY).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        dt = datetime.fromisoformat(f"{raw}T00:00:00").replace(tzinfo=NY)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    parsed = parse_utc(raw)
    if parsed is not None:
        return parsed.isoformat().replace("+00:00", "Z")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NY)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _time_on_date(day: date, time_text: str) -> datetime:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", time_text.strip())
    if not match:
        raise ValueError(f"invalid NY time: {time_text!r}")
    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3) or 0)
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=NY)


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _float_env(name: str, default: float, *, minimum: float) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except ValueError:
        return default


def _int_env(name: str, default: int, *, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _price(value: Any) -> str:
    if value is None:
        return "NA"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "NA"


def _number_text(value: Any) -> str:
    if value is None:
        return "NA"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return "NA"
