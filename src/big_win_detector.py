"""
Big-win detector: surfaces single-trade events that qualify as "big wins".

A big win is a closed trade where:
  • profit >= BIG_WIN_MIN_PROFIT_USDC
  • ROI    >= BIG_WIN_MIN_ROI_PCT
  • trade size (cost basis) >= BIG_WIN_MIN_TRADE_SIZE_USDC
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from . import config, polymarket_client as pm
from .models import BigWin, WalletStats
from .wallet_scanner import _parse_leaderboard_entry, _safe_float

logger = logging.getLogger(__name__)


def _closed_position_to_big_win(raw: dict[str, Any], wallet: str, display_name: str) -> Optional[BigWin]:
    """
    Try to extract a BigWin from a single raw closed-position dict.
    Returns None if the position doesn't qualify.
    """
    pnl = _safe_float(
        raw.get("pnl") or raw.get("profit") or raw.get("profitAndLoss") or raw.get("realizedPnl")
    )
    # cost basis: prefer explicit cost field, else derive from totalBought / avgPrice
    cost = _safe_float(raw.get("cost") or raw.get("invested") or raw.get("costBasis"))
    if not cost:
        total_bought = _safe_float(raw.get("totalBought") or raw.get("amount") or 0)
        avg_price = _safe_float(raw.get("avgPrice") or raw.get("price") or 0)
        if total_bought and avg_price:
            cost = total_bought * avg_price  # totalBought is absolute token amount, cost = tokens * avg price
        elif total_bought:
            cost = total_bought  # fallback: treat totalBought as USDC cost
    # outcome: try direct outcome, then YES/NO indicator, then outcomeIndex
    raw_outcome = raw.get("outcome") or ""
    if raw_outcome in ("", None):
        # Derive YES/NO from avgPrice: < 0.5 = NO side bought, > 0.5 = YES side bought
        ap = _safe_float(raw.get("avgPrice") or 0)
        if ap > 0.55:
            raw_outcome = "YES"
        elif ap > 0 and ap < 0.45:
            raw_outcome = "NO"
        else:
            raw_outcome = str(raw.get("outcomeIndex", "N/A"))
    outcome = str(raw_outcome)
    question = str(raw.get("question") or raw.get("title") or raw.get("marketTitle") or "Unknown")
    market_id = str(raw.get("market") or raw.get("marketId") or raw.get("conditionId") or "")
    trade_id = str(raw.get("id") or raw.get("tradeId") or "")
    timestamp = int(_safe_float(raw.get("timestamp") or raw.get("createdAt") or raw.get("time")))

    roi = (pnl / cost * 100) if cost > 0 else 0.0

    if (
        pnl >= config.BIG_WIN_MIN_PROFIT_USDC
        and roi >= config.BIG_WIN_MIN_ROI_PCT
        and cost >= config.BIG_WIN_MIN_TRADE_SIZE_USDC
    ):
        end_date  = str(raw.get("endDate") or "")
        # Skip markets resolved before Feb 1, 2025 — stale, no alert value
        # (still-open long-duration markets from 2025 are fine)
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                if end_dt < datetime(2025, 2, 1, tzinfo=timezone.utc):
                    return None
            except: pass
        avg_price = _safe_float(raw.get("avgPrice") or 0)
        return BigWin(
            wallet=wallet,
            display_name=display_name,
            market_question=question,
            outcome=outcome,
            profit_usdc=pnl,
            roi_pct=roi,
            trade_size_usdc=cost,
            timestamp=timestamp,
            market_id=market_id,
            trade_id=trade_id,
            end_date=end_date,
            avg_price=avg_price,
        )
    return None


def _leaderboard_wallet_to_big_wins(entry_raw: dict[str, Any], rank: int) -> list[BigWin]:
    """
    For a single leaderboard entry: fetch their closed positions and
    surface any that qualify as big wins.
    """
    entry = _parse_leaderboard_entry(entry_raw, rank)
    if not entry.proxy_wallet:
        return []

    big_wins: list[BigWin] = []
    closed = pm.get_user_closed_positions(entry.proxy_wallet)
    for pos in closed:
        bw = _closed_position_to_big_win(pos, entry.proxy_wallet, entry.name)
        if bw:
            bw.leaderboard_volume = entry.volume_usdc
            big_wins.append(bw)

    # Use OMPA-backed LIFETIME win rate (replaces 30-day window)
    # The 30-day window gives misleading 100% for whales with few recent trades.
    # Cumulative stats improve with every scan.
    from wallet_profiles import get_profile, update_profile
    profile = get_profile(entry.proxy_wallet)
    profile.name = entry.name  # keep name fresh
    # Pass ALL closed positions at once — merge_positions dedupes and recalculates
    if closed:
        update_profile(entry.proxy_wallet, entry.name, closed)
    # Assign lifetime win rate to all big wins from this wallet
    lifetime_rate = profile.win_rate
    for bw in big_wins:
        bw.win_rate = lifetime_rate
        bw.win_rate_30d = profile.win_rate_30d
        bw.win_streak = profile.current_streak

    return big_wins


def scan_big_wins_from_leaderboard(
    top_n: int = config.LEADERBOARD_TOP_N,
) -> list[BigWin]:
    """
    Pull the top-N leaderboard wallets and find all big-win trades across them.
    Returns a list of BigWin objects sorted by profit descending.
    """
    raw_entries = pm.get_leaderboard(limit=top_n)
    if not raw_entries:
        logger.warning("Leaderboard returned no data — cannot scan big wins.")
        return []

    all_big_wins: list[BigWin] = []
    for idx, raw in enumerate(raw_entries[:top_n], start=1):
        wins = _leaderboard_wallet_to_big_wins(raw, idx)
        all_big_wins.extend(wins)

    all_big_wins.sort(key=lambda bw: bw.profit_usdc, reverse=True)
    return all_big_wins


def scan_big_wins_for_wallet(wallet: str, display_name: str = "") -> list[BigWin]:
    """
    Find all big-win trades for a single wallet address.
    """
    big_wins: list[BigWin] = []

    closed = pm.get_user_closed_positions(wallet)
    for pos in closed:
        bw = _closed_position_to_big_win(pos, wallet, display_name or wallet[:12] + "…")
        if bw:
            big_wins.append(bw)

    big_wins.sort(key=lambda bw: bw.profit_usdc, reverse=True)
    return big_wins


def scan_big_wins_for_market(market_id: str, top_holders: int = 20) -> list[BigWin]:
    """
    Find big wins inside a specific market by scanning its top holders.
    """
    holders = pm.get_market_holders(market_id, limit=top_holders)
    big_wins: list[BigWin] = []

    for holder in holders:
        wallet = str(
            holder.get("proxyWallet")
            or holder.get("proxy_wallet")
            or holder.get("address")
            or holder.get("user")
            or ""
        )
        name = str(holder.get("name") or holder.get("displayName") or "")
        if not wallet:
            continue
        closed = pm.get_user_closed_positions(wallet)
        for pos in closed:
            mid = str(pos.get("market") or pos.get("marketId") or "")
            if mid and mid != market_id:
                continue
            bw = _closed_position_to_big_win(pos, wallet, name)
            if bw:
                big_wins.append(bw)

    big_wins.sort(key=lambda bw: bw.profit_usdc, reverse=True)
    return big_wins


def annotate_wallet_big_wins(stats: WalletStats, big_wins: list[BigWin]) -> WalletStats:
    """Attach big-win count to an existing WalletStats object."""
    stats.big_win_count = len(big_wins)
    if big_wins:
        stats.biggest_win_usdc = max(stats.biggest_win_usdc, big_wins[0].profit_usdc)
    return stats
