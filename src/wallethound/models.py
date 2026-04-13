"""
WalletHound data models.

All models are pure dataclasses with no external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class WalletTier(str, Enum):
    """Classification tier for a tracked wallet."""

    BIG_WINNER = "big_winner"
    CONSISTENT_WINNER = "consistent_winner"
    COMPOUNDER = "compounder"


@dataclass
class DepositWithdrawal:
    """A single deposit or withdrawal event (non-trade USDC movement)."""

    wallet: str
    tx_type: str  # "deposit" or "withdrawal"
    amount_usdc: float
    timestamp: int
    tx_id: str = ""


@dataclass
class BalanceSnapshot:
    """Point-in-time balance snapshot for a wallet."""

    wallet: str
    timestamp: int
    total_balance_usdc: float
    deposits_cumulative: float = 0.0
    withdrawals_cumulative: float = 0.0

    @property
    def organic_balance(self) -> float:
        """Balance attributable to wins only (excluding net deposits)."""
        net_deposits = self.deposits_cumulative - self.withdrawals_cumulative
        return self.total_balance_usdc - net_deposits


@dataclass
class ConsistencyScore:
    """Metrics that measure how consistently a wallet wins."""

    wallet: str
    display_name: str = ""
    total_resolved_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate_pct: float = 0.0
    longest_win_streak: int = 0
    current_win_streak: int = 0
    avg_win_usdc: float = 0.0
    avg_loss_usdc: float = 0.0
    profit_factor: float = 0.0  # gross_wins / gross_losses
    consistency_score: float = 0.0  # composite 0–100 score
    total_profit_usdc: float = 0.0
    total_volume_usdc: float = 0.0


@dataclass
class GrowthMetrics:
    """Metrics for wallet balance growth / compounding analysis."""

    wallet: str
    display_name: str = ""
    starting_balance_usdc: float = 0.0
    current_balance_usdc: float = 0.0
    total_deposits_usdc: float = 0.0
    total_withdrawals_usdc: float = 0.0
    organic_growth_usdc: float = 0.0  # growth from wins only
    organic_growth_pct: float = 0.0
    total_profit_usdc: float = 0.0
    num_winning_periods: int = 0
    num_periods: int = 0
    compounding_score: float = 0.0  # 0–100, higher = more consistent compounding
    balance_snapshots: list[BalanceSnapshot] = field(default_factory=list)


@dataclass
class HoundResult:
    """A single wallet result from WalletHound scanning."""

    wallet: str
    display_name: str = ""
    tiers: list[WalletTier] = field(default_factory=list)
    total_profit_usdc: float = 0.0
    total_volume_usdc: float = 0.0
    total_trades: int = 0
    win_rate_pct: float = 0.0
    # Big-winner metrics
    biggest_win_usdc: float = 0.0
    big_win_count: int = 0
    # Consistency metrics
    consistency_score: float = 0.0
    longest_win_streak: int = 0
    profit_factor: float = 0.0
    # Compounder metrics
    organic_growth_pct: float = 0.0
    compounding_score: float = 0.0
    total_deposits_usdc: float = 0.0
    total_withdrawals_usdc: float = 0.0
    organic_growth_usdc: float = 0.0

    @property
    def tier_labels(self) -> str:
        """Human-readable tier labels."""
        labels = {
            WalletTier.BIG_WINNER: "🏆 Big Winner",
            WalletTier.CONSISTENT_WINNER: "🎯 Consistent",
            WalletTier.COMPOUNDER: "📈 Compounder",
        }
        return ", ".join(labels.get(t, t.value) for t in self.tiers) if self.tiers else "—"
