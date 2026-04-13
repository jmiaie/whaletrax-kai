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


def _get(url: str, params: Optional[dict] = None) -> Any:
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


def _paginate(url: str, params: dict, key: Optional[str] = None) -> list[dict]:
    """
    Fetch all pages from a paginated endpoint.

    Stops when fewer results than `limit` are returned or `MAX_PAGES` is hit.
    If *key* is provided the response is expected to be a dict and the list
    lives at ``response[key]``; otherwise the response itself must be a list.
    """
    results: list[dict] = []
    offset = 0
    limit = params.get("limit", config.DEFAULT_PAGE_LIMIT)
    for page in range(config.MAX_PAGES):
        params["offset"] = offset
        data = _get(url, params)
        if data is None:
            break
        page_items: list[dict] = data[key] if key else data
        if not isinstance(page_items, list):
            break
        results.extend(page_items)
        if len(page_items) < limit:
            break
        offset += limit
    return results


# ── Gamma API ────────────────────────────────────────────────────────────────

def get_markets(closed: bool = False, limit: int = 100) -> list[dict]:
    """Return a list of Polymarket markets."""
    url = f"{config.GAMMA_API_BASE}/markets"
    params: dict = {"closed": str(closed).lower(), "limit": limit}
    return _paginate(url, params)


def get_market(market_id: str) -> Optional[dict]:
    """Return metadata for a single market."""
    url = f"{config.GAMMA_API_BASE}/markets/{market_id}"
    return _get(url)


def get_events(limit: int = 100) -> list[dict]:
    """Return a list of Polymarket events."""
    url = f"{config.GAMMA_API_BASE}/events"
    params: dict = {"limit": limit}
    return _paginate(url, params)


# ── Data API ─────────────────────────────────────────────────────────────────

def get_leaderboard(limit: int = config.LEADERBOARD_TOP_N) -> list[dict]:
    """Return the Polymarket profit leaderboard."""
    url = f"{config.DATA_API_BASE}/leaderboard"
    data = _get(url, {"limit": limit})
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Some endpoint versions wrap the list
        for key in ("leaderboard", "data", "results"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def get_user_trades(wallet: str, limit: int = config.DEFAULT_PAGE_LIMIT) -> list[dict]:
    """Return all trades for *wallet* (proxy address)."""
    url = f"{config.DATA_API_BASE}/trades"
    params: dict = {"user": wallet, "limit": limit}
    return _paginate(url, params)


def get_user_positions(wallet: str) -> list[dict]:
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


def get_user_closed_positions(wallet: str, limit: int = config.DEFAULT_PAGE_LIMIT) -> list[dict]:
    """Return closed/resolved positions for *wallet*."""
    url = f"{config.DATA_API_BASE}/closed-positions"
    params: dict = {"user": wallet, "limit": limit}
    raw = _paginate(url, params)
    # Some API versions wrap under "positions"
    if raw and isinstance(raw[0], dict) and "positions" in raw[0]:
        return raw[0]["positions"]
    return raw


def get_user_value(wallet: str) -> Optional[dict]:
    """Return portfolio value summary for *wallet*."""
    url = f"{config.DATA_API_BASE}/value"
    return _get(url, {"user": wallet})


def get_user_activity(wallet: str, limit: int = config.DEFAULT_PAGE_LIMIT) -> list[dict]:
    """Return on-chain activity (claims, redemptions) for *wallet*."""
    url = f"{config.DATA_API_BASE}/activity"
    params: dict = {"user": wallet, "limit": limit}
    return _paginate(url, params)


def get_market_holders(market_id: str, limit: int = config.MARKET_TOP_HOLDERS_N) -> list[dict]:
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

def get_clob_market_trades(market_id: str, limit: int = config.DEFAULT_PAGE_LIMIT) -> list[dict]:
    """Return recent trades for a market from the CLOB."""
    url = f"{config.CLOB_API_BASE}/trades"
    params: dict = {"market_id": market_id, "limit": limit}
    data = _get(url, params)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("trades", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def get_order_book(token_id: str) -> Optional[dict]:
    """Return the live order book for a market outcome token."""
    url = f"{config.CLOB_API_BASE}/order-book/{token_id}"
    return _get(url)
