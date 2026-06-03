"""
Polymarket API client.

Wraps the three public Polymarket APIs:
  • Gamma API  – market metadata, events, prices
  • Data API   – user trades, positions, leaderboard
  • CLOB API   – live order book, recent market trades

All read-only endpoints are used; no authentication is required.
"""

from __future__ import annotations

import time
import logging
from typing import Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import config

logger = logging.getLogger(__name__)


def _build_session() -> requests.Session:
    """Return a requests Session with automatic retry logic."""
    session = requests.Session()
    retry = Retry(
        total=config.MAX_RETRIES,
        backoff_factor=config.RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({"Accept": "application/json"})
    return session


_session = _build_session()


def _get(url: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any] | list[dict[str, Any]] | None:
    """Perform a GET request and return parsed JSON, or None on error."""
    try:
        resp = _session.get(url, params=params, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as exc:
        logger.warning("HTTP error %s for %s", exc.response.status_code, url)
        return None
    except requests.exceptions.RequestException as exc:
        logger.warning("Request failed for %s: %s", url, exc)
        return None


def _paginate(url: str, params: dict[str, Any], key: Optional[str] = None,
               max_records: Optional[int] = None) -> list[dict[str, Any]]:
    """
    Fetch ALL pages from a paginated endpoint.

    Polymarket caps at 50 items/page regardless of limit param.
    Loops until page < 50 items, MAX_PAGES (200), or max_records cap.
    """
    results: list[dict[str, Any]] = []
    offset = 0
    hard_cap = max_records or config.MAX_RECORDS_PER_QUERY
    for page in range(config.MAX_PAGES):
        page_params = {**params, "offset": offset, "limit": config.DEFAULT_PAGE_LIMIT}
        data = _get(url, page_params)
        if data is None:
            break
        page_items: list[dict[str, Any]] = data[key] if key else data
        if not isinstance(page_items, list) or not page_items:
            break
        results.extend(page_items)
        if len(page_items) < config.DEFAULT_PAGE_LIMIT:
            # Partial page = end of data
            break
        if len(results) >= hard_cap:
            results = results[:hard_cap]
            break
        offset += config.DEFAULT_PAGE_LIMIT
    return results


# ── Gamma API ────────────────────────────────────────────────────────────────

def get_markets(closed: bool = False, limit: int = 100) -> list[dict[str, Any]]:
    """Return a list of Polymarket markets."""
    url = f"{config.GAMMA_API_BASE}/markets"
    params: dict[str, Any] = {"closed": str(closed).lower(), "limit": limit}
    return _paginate(url, params)


def get_market(market_id: str) -> Optional[dict[str, Any]]:
    """Return metadata for a single market."""
    url = f"{config.GAMMA_API_BASE}/markets/{market_id}"
    return _get(url)


# ── Data API ─────────────────────────────────────────────────────────────────

def get_leaderboard(limit: int = config.LEADERBOARD_TOP_N) -> list[dict[str, Any]]:
    """Return the Polymarket profit leaderboard."""
    url = f"{config.DATA_API_BASE}/v1/leaderboard"
    data = _get(url, {"limit": limit})
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Some endpoint versions wrap the list
        for key in ("leaderboard", "data", "results"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def get_user_trades(wallet: str, limit: int = config.DEFAULT_PAGE_LIMIT) -> list[dict[str, Any]]:
    """Return all trades for *wallet* (proxy address)."""
    url = f"{config.DATA_API_BASE}/trades"
    params: dict[str, Any] = {"user": wallet, "limit": limit}
    return _paginate(url, params)


def get_user_positions(wallet: str) -> list[dict[str, Any]]:
    """Return open positions for *wallet*."""
    url = f"{config.DATA_API_BASE}/positions"
    data = _get(url, {"user": wallet})
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("positions", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def get_user_closed_positions(wallet: str, limit: int = 5000) -> list[dict[str, Any]]:
    """Return ALL closed/resolved positions for *wallet*, paginating all pages.
    
    Polymarket API caps at 50 items/page. Loops up to MAX_PAGES (200) or *limit*,
    whichever comes first. Default 5000, hard cap 10000 from config.
    Results sorted oldest-first internally by the API.
    """
    url = f"{config.DATA_API_BASE}/v1/closed-positions"
    params: dict[str, Any] = {"user": wallet}
    max_r = min(limit, config.MAX_RECORDS_PER_QUERY)
    raw = _paginate(url, params, max_records=max_r)
    return raw


def get_user_value(wallet: str) -> Optional[dict[str, Any]]:
    """Return portfolio value summary for *wallet*."""
    url = f"{config.DATA_API_BASE}/value"
    return _get(url, {"user": wallet})


def get_user_activity(wallet: str, limit: int = config.DEFAULT_PAGE_LIMIT) -> list[dict[str, Any]]:
    """Return on-chain activity (claims, redemptions) for *wallet*."""
    url = f"{config.DATA_API_BASE}/activity"
    params: dict[str, Any] = {"user": wallet, "limit": limit}
    return _paginate(url, params)


def get_market_holders(market_id: str, limit: int = config.MARKET_TOP_HOLDERS_N) -> list[dict[str, Any]]:
    """Return top holders for a specific market."""
    url = f"{config.DATA_API_BASE}/holders"
    data = _get(url, {"market": market_id, "limit": limit})
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("holders", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


# ── CLOB API ──────────────────────────────────────────────────────────────────
