"""
Consistent-winner detector for WalletHound.

Scores wallets on the *consistency* of their winning, not just raw profit.
A wallet with a 70 % win-rate over 50+ trades is more interesting than one
with a single lucky 10 000 USDC hit.

Key metrics
-----------
- Win rate (%)
- Longest win streak
- Profit factor  (gross_wins / gross_losses)
- Average win vs average loss
- Composite consistency score (0–100)
"""

from __future__ import annotations

import logging
import math

from .. import polymarket_client as pm
from ..wallet_scanner import _safe_float
from ..models import ConsistencyScore

logger = logging.getLogger(__name__)

# Minimum number of resolved positions to be considered for consistency ranking
MIN_RESOLVED_POSITIONS = 5


def _compute_streaks(pnl_sequence: list[float]) -> tuple[int, int]:
    """
    Return ``(longest_win_streak, current_win_streak)`` from a chronological
    sequence of per-position P&L values.
    """
    longest = 0
    current = 0
    for pnl in pnl_sequence:
        if pnl > 0:
            current += 1
            if current > longest:
                longest = current
        else:
            current = 0
    return longest, current


def _composite_score(
    win_rate: float,
    profit_factor: float,
    longest_streak: int,
    trade_count: int,
) -> float:
    """
    Compute a composite consistency score in [0, 100].

    Components (weighted):
      40 % — win rate scaled to [0, 100]
      25 % — profit factor (capped at 5× for scoring)
      20 % — longest win streak (log-scaled, capped at 20)
      15 % — trade count confidence (log-scaled, capped at 200)
    """
    wr_component = min(win_rate, 100.0)

    pf_capped = min(profit_factor, 5.0)
    pf_component = (pf_capped / 5.0) * 100.0

    streak_capped = min(longest_streak, 20)
    streak_component = (math.log1p(streak_capped) / math.log1p(20)) * 100.0

    count_capped = min(trade_count, 200)
    count_component = (math.log1p(count_capped) / math.log1p(200)) * 100.0

    score = (
        0.40 * wr_component
        + 0.25 * pf_component
        + 0.20 * streak_component
        + 0.15 * count_component
    )
    return round(min(score, 100.0), 1)


def score_wallet(wallet: str, display_name: str = "") -> ConsistencyScore:
    """
    Compute consistency metrics for a single wallet from its closed positions.
    """
    closed = pm.get_user_closed_positions(wallet)

    pnl_values: list[float] = []
    gross_wins = 0.0
    gross_losses = 0.0
    total_volume = 0.0

    for pos in closed:
        pnl = _safe_float(
            pos.get("pnl") or pos.get("profit") or pos.get("profitAndLoss")
            or pos.get("realizedPnl")
        )
        cost = _safe_float(pos.get("cost") or pos.get("invested") or pos.get("costBasis"))
        total_volume += cost
        pnl_values.append(pnl)

        if pnl > 0:
            gross_wins += pnl
        elif pnl < 0:
            gross_losses += abs(pnl)

    total = len(pnl_values)
    wins = sum(1 for p in pnl_values if p > 0)
    losses = sum(1 for p in pnl_values if p < 0)
    win_rate = (wins / total * 100) if total > 0 else 0.0
    avg_win = (gross_wins / wins) if wins > 0 else 0.0
    avg_loss = (gross_losses / losses) if losses > 0 else 0.0
    profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else (
        float("inf") if gross_wins > 0 else 0.0
    )

    longest_streak, current_streak = _compute_streaks(pnl_values)

    # Cap infinite profit factor for scoring
    pf_for_score = profit_factor if math.isfinite(profit_factor) else 5.0

    consistency = _composite_score(win_rate, pf_for_score, longest_streak, total)

    return ConsistencyScore(
        wallet=wallet,
        display_name=display_name,
        total_resolved_trades=total,
        winning_trades=wins,
        losing_trades=losses,
        win_rate_pct=win_rate,
        longest_win_streak=longest_streak,
        current_win_streak=current_streak,
        avg_win_usdc=avg_win,
        avg_loss_usdc=avg_loss,
        profit_factor=round(profit_factor, 2) if math.isfinite(profit_factor) else 999.99,
        consistency_score=consistency,
        total_profit_usdc=gross_wins - gross_losses,
        total_volume_usdc=total_volume,
    )


def qualifies_as_consistent(score: ConsistencyScore, min_score: float = 50.0) -> bool:
    """
    Return True if the wallet meets the threshold to be labelled a
    'consistent winner'.
    """
    return (
        score.total_resolved_trades >= MIN_RESOLVED_POSITIONS
        and score.win_rate_pct >= 55.0
        and score.consistency_score >= min_score
    )
