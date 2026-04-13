"""
Big-win detector: surfaces single-trade events that qualify as "big wins".

A big win is a closed trade where:
  • profit >= BIG_WIN_MIN_PROFIT_USDC
  • ROI    >= BIG_WIN_MIN_ROI_PCT
  • trade size (cost basis) >= BIG_WIN_MIN_TRADE_SIZE_USDC
"""

from __future__ import annotations

import logging
from typing import Optional

from . import config, polymarket_client as pm
from .models import BigWin, WalletStats
from .wallet_scanner import _parse_leaderboard_entry, _safe_float

logger = logging.getLogger(__name__)


def _closed_position_to_big_win(raw: dict, wallet: str, display_name: str) -> Optional[BigWin]:
    """
    Try to extract a BigWin from a single raw closed-position dict.
    Returns None if the position doesn't qualify.
    """
    pnl = _safe_float(
        raw.get("pnl") or raw.get("profit") or raw.get("profitAndLoss") or raw.get("realizedPnl")
    )
    cost = _safe_float(raw.get("cost") or raw.get("invested") or raw.get("costBasis"))
    outcome = str(raw.get("outcome") or raw.get("outcomeIndex") or "")
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
        )
    return None


def _leaderboard_wallet_to_big_wins(entry_raw: dict, rank: int) -> list[BigWin]:
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
            big_wins.append(bw)

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
        bw = _closed_position_to_big_win(pos, wallet, display_name or wallet[:10] + "…")
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
