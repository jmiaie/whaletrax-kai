"""
WalletHound scanner — orchestrates big-winner, consistent-winner, and
compounder detection across the Polymarket leaderboard.
"""

from __future__ import annotations

import logging
from typing import Optional

from .. import config, polymarket_client as pm
from ..big_win_detector import scan_big_wins_for_wallet
from ..wallet_scanner import _parse_leaderboard_entry, _safe_float
from . import compounders, consistent_winners
from .deposit_tracker import compute_totals, get_deposits_withdrawals
from .models import HoundResult, WalletTier

logger = logging.getLogger(__name__)

# Thresholds for tier classification
BIG_WINNER_MIN_PROFIT_USDC = float(config.BIG_WIN_MIN_PROFIT_USDC)
BIG_WINNER_MIN_BIG_WINS = 1
CONSISTENT_MIN_SCORE = 50.0
COMPOUNDER_MIN_SCORE = 40.0
COMPOUNDER_MIN_GROWTH_PCT = 10.0


def hound_wallet(wallet: str, display_name: str = "") -> HoundResult:
    """
    Full WalletHound analysis for a single wallet.

    Runs big-win detection, consistency scoring, and compounder analysis,
    then classifies the wallet into tiers.
    """
    result = HoundResult(wallet=wallet, display_name=display_name)

    # ── Big-winner analysis ──────────────────────────────────────────────
    big_wins = scan_big_wins_for_wallet(wallet, display_name)
    result.big_win_count = len(big_wins)
    if big_wins:
        result.biggest_win_usdc = big_wins[0].profit_usdc  # already sorted desc
    if result.big_win_count >= BIG_WINNER_MIN_BIG_WINS:
        result.tiers.append(WalletTier.BIG_WINNER)

    # ── Consistency analysis ─────────────────────────────────────────────
    cons = consistent_winners.score_wallet(wallet, display_name)
    result.consistency_score = cons.consistency_score
    result.longest_win_streak = cons.longest_win_streak
    result.profit_factor = cons.profit_factor
    result.win_rate_pct = cons.win_rate_pct
    result.total_trades = cons.total_resolved_trades
    result.total_profit_usdc = cons.total_profit_usdc
    result.total_volume_usdc = cons.total_volume_usdc

    if consistent_winners.qualifies_as_consistent(cons, min_score=CONSISTENT_MIN_SCORE):
        result.tiers.append(WalletTier.CONSISTENT_WINNER)

    # ── Compounder analysis ──────────────────────────────────────────────
    growth = compounders.analyse_wallet(wallet, display_name)
    result.organic_growth_pct = growth.organic_growth_pct
    result.organic_growth_usdc = growth.organic_growth_usdc
    result.compounding_score = growth.compounding_score
    result.total_deposits_usdc = growth.total_deposits_usdc
    result.total_withdrawals_usdc = growth.total_withdrawals_usdc

    if compounders.qualifies_as_compounder(
        growth,
        min_score=COMPOUNDER_MIN_SCORE,
        min_growth_pct=COMPOUNDER_MIN_GROWTH_PCT,
    ):
        result.tiers.append(WalletTier.COMPOUNDER)

    return result


def hound_leaderboard(
    top_n: int = config.LEADERBOARD_TOP_N,
    tier_filter: Optional[WalletTier] = None,
) -> list[HoundResult]:
    """
    Scan the top-N leaderboard wallets through all WalletHound detectors.

    If *tier_filter* is provided, only wallets matching that tier are returned.
    """
    raw_entries = pm.get_leaderboard(limit=top_n)
    if not raw_entries:
        logger.warning("Leaderboard returned no data for WalletHound scan.")
        return []

    results: list[HoundResult] = []
    for idx, raw in enumerate(raw_entries[:top_n], start=1):
        entry = _parse_leaderboard_entry(raw, rank=idx)
        if not entry.proxy_wallet:
            continue

        result = hound_wallet(entry.proxy_wallet, entry.name)
        if tier_filter is None or tier_filter in result.tiers:
            results.append(result)

    # Sort by total profit descending (primary), consistency score (secondary)
    results.sort(
        key=lambda r: (r.total_profit_usdc, r.consistency_score),
        reverse=True,
    )
    return results
