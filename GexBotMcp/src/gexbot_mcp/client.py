"""Small stdlib client for the GexBot HTTP API."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


PACKAGE_ROOT = Path(__file__).resolve().parents[2]


class GexBotApiError(RuntimeError):
    """Raised when GexBot returns an HTTP or transport failure."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class GexBotConfig:
    api_key: str | None
    api_v2_url: str = "https://api.gex.bot/v2"
    api_root_url: str = "https://api.gex.bot"
    user_agent: str = "HeatmapGexBotMcp/0.1"
    timeout_sec: float = 15.0

    @classmethod
    def from_env(cls, env_path: Path | None = None) -> "GexBotConfig":
        values = _read_env_file(env_path or PACKAGE_ROOT / ".env")
        values.update(os.environ)
        timeout_text = values.get("GEXBOT_TIMEOUT_SEC", "15")
        try:
            timeout_sec = float(timeout_text)
        except ValueError:
            timeout_sec = 15.0
        return cls(
            api_key=_clean(values.get("GEXBOT_API_KEY")),
            api_v2_url=_clean(values.get("GEXBOT_API_V2_URL")) or cls.api_v2_url,
            api_root_url=_clean(values.get("GEXBOT_API_ROOT_URL")) or cls.api_root_url,
            user_agent=_clean(values.get("GEXBOT_USER_AGENT")) or cls.user_agent,
            timeout_sec=max(1.0, timeout_sec),
        )

    @property
    def key_loaded(self) -> bool:
        return bool(self.api_key)

    @property
    def masked_key(self) -> str | None:
        if not self.api_key:
            return None
        if len(self.api_key) <= 12:
            return "***"
        prefix = "gexbot_custom_"
        visible = len(prefix) if self.api_key.startswith(prefix) else 13
        return f"{self.api_key[:visible]}...{self.api_key[-4:]}"


class GexBotClient:
    def __init__(self, config: GexBotConfig | None = None) -> None:
        self.config = config or GexBotConfig.from_env()

    def health(self, network_check: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": True,
            "key_loaded": self.config.key_loaded,
            "masked_key": self.config.masked_key,
            "api_v2_url": self.config.api_v2_url,
            "api_root_url": self.config.api_root_url,
            "user_agent": self.config.user_agent,
        }
        if network_check:
            try:
                tickers = self.tickers()
                result["network_check"] = {
                    "ok": True,
                    "stocks": len(tickers.get("stocks", [])),
                    "indexes": len(tickers.get("indexes", [])),
                    "futures": len(tickers.get("futures", [])),
                }
            except Exception as exc:  # pragma: no cover - live diagnostic
                result["ok"] = False
                result["network_check"] = {"ok": False, "error": str(exc)}
        return result

    def tickers(self) -> dict[str, Any]:
        return self._get_json(self._v2_url("/tickers"), auth=False)

    def categories(self, package: str) -> list[Any]:
        package = _require_enum(package, {"classic", "state", "orderflow"}, "package")
        return self._get_json(self._root_url(f"/{quote(package)}/categories"), auth=False)

    def chart(self, ticker: str, package: str, category: str) -> dict[str, Any]:
        package = _require_enum(package, {"classic", "state", "orderflow"}, "package")
        if package == "orderflow":
            return self.orderflow(ticker)
        return self._get_json(
            self._v2_url(f"/{_path(ticker)}/{quote(package)}/{_path(category)}"),
            auth=True,
        )

    def majors(self, ticker: str, package: str, category: str) -> dict[str, Any]:
        package = _require_enum(package, {"classic", "state"}, "package")
        return self._get_json(
            self._v2_url(f"/{_path(ticker)}/{quote(package)}/{_path(category)}/majors"),
            auth=True,
        )

    def maxchange(self, ticker: str, package: str, category: str) -> dict[str, Any]:
        package = _require_enum(package, {"classic", "state"}, "package")
        return self._get_json(
            self._v2_url(f"/{_path(ticker)}/{quote(package)}/{_path(category)}/maxchange"),
            auth=True,
        )

    def orderflow(self, ticker: str) -> dict[str, Any]:
        return self._get_json(
            self._v2_url(f"/{_path(ticker)}/orderflow/orderflow"),
            auth=True,
        )

    def _get_json(self, url: str, auth: bool) -> Any:
        if auth and not self.config.api_key:
            raise GexBotApiError("GEXBOT_API_KEY is not configured")
        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": "application/json",
        }
        if auth:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self.config.timeout_sec) as response:
                payload = response.read()
        except HTTPError as exc:
            body = _read_error_body(exc)
            raise GexBotApiError(
                f"GexBot HTTP {exc.code}: {body or exc.reason}",
                status=exc.code,
            ) from exc
        except URLError as exc:
            raise GexBotApiError(f"GexBot transport error: {exc.reason}") from exc

        try:
            return json.loads(payload.decode("utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise GexBotApiError(f"GexBot returned non-JSON payload from {url}") from exc

    def _v2_url(self, path: str) -> str:
        return f"{self.config.api_v2_url.rstrip('/')}/{path.lstrip('/')}"

    def _root_url(self, path: str) -> str:
        return f"{self.config.api_root_url.rstrip('/')}/{path.lstrip('/')}"


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _path(value: str) -> str:
    value = _clean(value)
    if not value:
        raise ValueError("path value must not be empty")
    return quote(value.upper(), safe="")


def _require_enum(value: str, allowed: set[str], name: str) -> str:
    normalized = (_clean(value) or "").lower()
    if normalized not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(sorted(allowed))}")
    return normalized


def _read_error_body(exc: HTTPError) -> str:
    try:
        raw = exc.read()
    except Exception:
        return ""
    if not raw:
        return ""
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        return raw.decode("utf-8", errors="replace")[:500]
    if isinstance(data, dict):
        return str(data.get("error") or data.get("message") or data)[:500]
    return str(data)[:500]
