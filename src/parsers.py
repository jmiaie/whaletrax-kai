"""
Parsing logic for raw Polymarket API responses.
"""

from __future__ import annotations

from typing import Any, Optional
from .models import LeaderboardEntry, Position, Trade


def _safe_float(val: object, default: float = 0.0) -> float:
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def parse_leaderboard_entry(raw: dict[str, Any], rank: int) -> LeaderboardEntry:
    return LeaderboardEntry(
        rank=rank,
        name=raw.get("name") or raw.get("displayName") or "",
        proxy_wallet=(
            raw.get("proxyWallet")
            or raw.get("proxy_wallet")
            or raw.get("address")
            or raw.get("user")
            or ""
        ),
        profit_usdc=_safe_float(raw.get("profitAndLoss") or raw.get("profit") or raw.get("pnl")),
        volume_usdc=_safe_float(raw.get("volume") or raw.get("volumeTraded")),
        trades=int(_safe_float(raw.get("trades") or raw.get("numTrades"))),
    )


def parse_trade(raw: dict[str, Any], wallet: str) -> Optional[Trade]:
    """Convert a raw API trade dict into a Trade model. Returns None if unparseable."""
    trade_id = str(raw.get("id") or raw.get("trade_id") or raw.get("tradeId") or "")
    market_id = str(
        raw.get("market") or raw.get("marketId") or raw.get("conditionId") or ""
    )
    outcome = str(raw.get("outcome") or raw.get("side") or raw.get("outcomeIndex") or "")
    side = str(raw.get("type") or raw.get("tradeType") or raw.get("side") or "").lower()
    size = _safe_float(raw.get("size") or raw.get("shares"))
    price = _safe_float(raw.get("price") or raw.get("avgPrice"))
    amount = _safe_float(raw.get("amount") or raw.get("usdcAmount") or raw.get("value"))
    if amount == 0.0 and size > 0 and price > 0:
        amount = size * price
    timestamp = int(_safe_float(raw.get("timestamp") or raw.get("createdAt") or raw.get("time")))
    question = str(raw.get("question") or raw.get("title") or raw.get("marketTitle") or "")

    if not market_id and not question:
        return None

    return Trade(
        trade_id=trade_id,
        wallet=wallet,
        market_id=market_id,
        market_question=question,
        outcome=outcome,
        side=side,
        size=size,
        price=price,
        amount_usdc=amount,
        timestamp=timestamp,
    )


def parse_position(raw: dict[str, Any], wallet: str) -> Optional[Position]:
    market_id = str(
        raw.get("market") or raw.get("marketId") or raw.get("conditionId") or ""
    )
    outcome = str(raw.get("outcome") or raw.get("outcomeIndex") or "")
    size = _safe_float(raw.get("size") or raw.get("shares"))
    avg_price = _safe_float(raw.get("avgPrice") or raw.get("averagePrice") or raw.get("price"))
    current_price = _safe_float(
        raw.get("currentPrice") or raw.get("lastPrice") or raw.get("price")
    )
    cost = _safe_float(raw.get("cost") or raw.get("invested"))
    if cost == 0.0 and size > 0 and avg_price > 0:
        cost = size * avg_price
    value = _safe_float(raw.get("value") or raw.get("currentValue"))
    if value == 0.0 and size > 0 and current_price > 0:
        value = size * current_price
    question = str(raw.get("question") or raw.get("title") or raw.get("marketTitle") or "")

    return Position(
        wallet=wallet,
        market_id=market_id,
        market_question=question,
        outcome=outcome,
        size=size,
        avg_price=avg_price,
        current_price=current_price,
        value_usdc=value,
        cost_usdc=cost,
        unrealised_pnl=value - cost,
        is_closed=bool(raw.get("isClosed") or raw.get("closed")),
    )
