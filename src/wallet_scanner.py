"""
Wallet scanner: builds WalletStats from Polymarket data.

Two entry points:
  • scan_leaderboard()  – pulls the top-N from the leaderboard and enriches each wallet
  • scan_wallet(address) – deep dive on a single wallet
"""

from __future__ import annotations

import logging
from typing import Optional

from . import config, polymarket_client as pm
from .models import LeaderboardEntry, Position, Trade, WalletStats

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_float(val: object, default: float = 0.0) -> float:
    try:
        return float(val)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _parse_leaderboard_entry(raw: dict[str, Any], rank: int) -> LeaderboardEntry:
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
        volume_usdc=_safe_float(raw.get("vol") or raw.get("volume") or raw.get("volumeTraded")),
        trades=int(_safe_float(raw.get("trades") or raw.get("numTrades"))),
    )


def _parse_trade(raw: dict[str, Any], wallet: str) -> Optional[Trade]:
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


def _parse_position(raw: dict[str, Any], wallet: str) -> Optional[Position]:
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


def _compute_stats_from_trades(wallet: str, trades: list[Trade]) -> WalletStats:
    """Aggregate a list of Trade objects into WalletStats."""
    stats = WalletStats(wallet=wallet)
    roi_sum = 0.0
    for t in trades:
        stats.total_volume_usdc += t.amount_usdc
        stats.total_trades += 1
        if t.profit_usdc > 0:
            stats.winning_trades += 1
            stats.total_profit_usdc += t.profit_usdc
            if t.profit_usdc > stats.biggest_win_usdc:
                stats.biggest_win_usdc = t.profit_usdc
        elif t.profit_usdc < 0:
            stats.losing_trades += 1
            stats.total_profit_usdc += t.profit_usdc  # adds negative
            if t.profit_usdc < stats.biggest_loss_usdc:
                stats.biggest_loss_usdc = t.profit_usdc
        roi_sum += t.roi_pct
    if stats.total_trades > 0:
        stats.win_rate_pct = (stats.winning_trades / stats.total_trades) * 100
        stats.avg_roi_pct = roi_sum / stats.total_trades
    return stats


def _enrich_stats_from_closed_positions(stats: WalletStats, positions: list[dict[str, Any]]) -> WalletStats:
    """
    Use the richer closed-positions endpoint (which already contains realised P&L)
    when available, to fill in WalletStats more accurately.
    """
    total_pnl = 0.0
    total_volume = 0.0
    wins = 0
    losses = 0
    best = 0.0
    worst = 0.0
    roi_sum = 0.0
    count = 0

    for raw in positions:
        pnl = _safe_float(
            raw.get("pnl") or raw.get("profit") or raw.get("profitAndLoss") or raw.get("realizedPnl")
        )
        size_cost = _safe_float(raw.get("cost") or raw.get("invested") or raw.get("costBasis"))
        volume = _safe_float(raw.get("value") or raw.get("currentValue") or size_cost)
        total_pnl += pnl
        total_volume += volume
        count += 1
        if pnl > 0:
            wins += 1
            if pnl > best:
                best = pnl
        elif pnl < 0:
            losses += 1
            if pnl < worst:
                worst = pnl
        if size_cost > 0:
            roi_sum += (pnl / size_cost) * 100

    if count > 0:
        stats.total_profit_usdc = total_pnl
        stats.total_volume_usdc = total_volume
        stats.total_trades = count
        stats.winning_trades = wins
        stats.losing_trades = losses
        stats.biggest_win_usdc = best
        stats.biggest_loss_usdc = worst
        stats.win_rate_pct = (wins / count * 100) if count else 0.0
        stats.avg_roi_pct = roi_sum / count if count else 0.0
    return stats


# ── Public API ────────────────────────────────────────────────────────────────



def _get_internal_whale_records(top_n: int | None = None) -> list[WalletStats]:
    """Fallback leaderboard sourced from wallet_tracker.db internal_whale_wallets."""
    import sqlite3
    from pathlib import Path
    db_path = Path(__file__).resolve().parents[1] / 'wallet_tracker.db'
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    q = 'SELECT wallet_address, display_name, lifetime_pnl, lifetime_wr, wr_30d, pnl_30d, total_trades, wins, losses, avg_roi, best_roi_trade, streak_current, streak_best, last_seen, updated_at, is_active FROM internal_whale_wallets ORDER BY lifetime_pnl DESC, lifetime_wr DESC, total_trades DESC'
    if top_n:
        q += f' LIMIT {int(top_n)}'
    rows = conn.execute(q).fetchall()
    conn.close()
    out = []
    for idx, r in enumerate(rows, start=1):
        s = WalletStats(wallet=r['wallet_address'], display_name=r['display_name'] or '', total_profit_usdc=float(r['lifetime_pnl'] or 0), total_trades=int(r['total_trades'] or 0), rank=idx)
        s.winning_trades = int(r['wins'] or 0)
        s.losing_trades = int(r['losses'] or 0)
        s.win_rate_pct = float(r['lifetime_wr'] or 0)
        s.avg_roi_pct = float(r['avg_roi'] or 0)
        s.biggest_win_usdc = float(r['best_roi_trade'] or 0)
        s.big_win_count = 0
        s.total_volume_usdc = float(r['pnl_30d'] or 0)
        setattr(s, 'win_rate_30d', float(r['wr_30d'] or 0))
        setattr(s, 'pnl_30d', float(r['pnl_30d'] or 0))
        out.append(s)
    return out

def scan_leaderboard(top_n: int = config.LEADERBOARD_TOP_N) -> list[WalletStats]:
    """
    Fetch the Polymarket leaderboard and return a ranked list of WalletStats.
    Prefer internal leaderboard data when available; fall back to Polymarket public ranks.
    """
    internal = _get_internal_whale_records(top_n=top_n)
    if internal:
        return internal

    raw_entries = pm.get_leaderboard(limit=top_n)
    if not raw_entries:
        logger.warning("Leaderboard returned no data.")
        return []

    results: list[WalletStats] = []
    for idx, raw in enumerate(raw_entries[:top_n], start=1):
        entry = _parse_leaderboard_entry(raw, rank=idx)
        if not entry.proxy_wallet:
            continue

        stats = WalletStats(
            wallet=entry.proxy_wallet,
            display_name=entry.name,
            total_profit_usdc=entry.profit_usdc,
            total_volume_usdc=entry.volume_usdc,
            total_trades=entry.trades,
            rank=entry.rank,
        )
        if stats.total_volume_usdc > 0:
            stats.win_rate_pct = 0.0
        results.append(stats)

    return results


def scan_wallet(wallet: str) -> WalletStats:
    """
    Deep-dive analysis of a single wallet address.

    Fetches trades AND closed positions, then computes aggregated stats.
    """
    logger.info("Scanning wallet %s …", wallet)
    stats = WalletStats(wallet=wallet)

    # Try the richer closed-positions first
    closed_raw = pm.get_user_closed_positions(wallet)
    if closed_raw:
        stats = _enrich_stats_from_closed_positions(stats, closed_raw)

    # Fall back to raw trades if we got nothing useful
    if stats.total_trades == 0:
        raw_trades = pm.get_user_trades(wallet, limit=config.WALLET_SCAN_MAX_TRADES)
        trades = [t for raw in raw_trades if (t := _parse_trade(raw, wallet)) is not None]
        # Compute P&L from buy→sell pairs grouped by market+outcome
        trades = _compute_realised_pnl(trades)
        stats = _compute_stats_from_trades(wallet, trades)

    # Overlay name from leaderboard if not set
    if not stats.display_name:
        value_data = pm.get_user_value(wallet)
        if isinstance(value_data, dict):
            stats.display_name = (
                value_data.get("displayName")
                or value_data.get("name")
                or value_data.get("username")
                or ""
            )

    stats.wallet = wallet
    return stats


def _compute_realised_pnl(trades: list[Trade]) -> list[Trade]:
    """
    Simple FIFO matching: pair opening (buy) trades with closing (sell) trades
    per (market_id, outcome) to estimate realised P&L.

    Polymarket trade records may use a variety of side labels depending on the
    API endpoint.  The mapping applied here is:
      - Opening legs  → side is "buy"  (position entered by purchasing shares)
      - Closing legs  → side is "sell" (position exited by selling shares back)

    Unknown or empty side values are treated as opening legs as a best-effort
    fallback (they cannot be matched to a known closing event).
    """
    from collections import defaultdict

    # Bucket opening (buy) trades by (market_id, outcome)
    buys: dict[tuple[str, str], list[Trade]] = defaultdict(list)
    for trade in trades:
        key = (trade.market_id, trade.outcome)
        # Treat "buy" and unknown sides as opening legs
        if trade.side in ("buy", ""):
            buys[key].append(trade)

    # Match closing (sell) trades against the earliest opening leg
    for trade in trades:
        key = (trade.market_id, trade.outcome)
        if trade.side == "sell" and buys[key]:
            buy = buys[key].pop(0)
            cost = buy.amount_usdc
            proceeds = trade.amount_usdc
            trade.profit_usdc = proceeds - cost
            if cost > 0:
                trade.roi_pct = ((proceeds - cost) / cost) * 100

    return trades
