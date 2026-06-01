"""
Data models used throughout WhaleTrax.
Pure dataclasses – no external dependencies.
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
class Trade:
    """A single resolved/closed trade for a wallet."""

    trade_id: str
    wallet: str
    market_id: str
    market_question: str
    outcome: str                  # "Yes" / "No" / outcome label
    side: str                     # "buy" or "sell"
    size: float                   # shares transacted
    price: float                  # average fill price (0–1)
    amount_usdc: float            # total USDC value = size * price
    timestamp: int                # unix timestamp
    profit_usdc: float = 0.0      # realised P&L for this trade leg (set post-processing)
    roi_pct: float = 0.0          # return-on-investment %  (set post-processing)


@dataclass
class Position:
    """An open or closed position held by a wallet."""

    wallet: str
    market_id: str
    market_question: str
    outcome: str
    size: float                   # shares held
    avg_price: float              # average entry price
    current_price: float          # current market price
    value_usdc: float             # current mark-to-market value
    cost_usdc: float              # total cost basis
    unrealised_pnl: float         # current_value - cost_basis
    is_closed: bool = False


@dataclass
class WalletStats:
    """Aggregated statistics for a single wallet address."""

    wallet: str
    display_name: str = ""
    total_profit_usdc: float = 0.0
    total_volume_usdc: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    biggest_win_usdc: float = 0.0
    biggest_loss_usdc: float = 0.0
    win_rate_pct: float = 0.0
    avg_roi_pct: float = 0.0
    rank: int = 0
    big_win_count: int = 0        # trades that qualify as "big wins"
    inverse_candidate: bool = False
    inverse_reason: str = ""

    @property
    def net_roi_pct(self) -> float:
        if self.total_volume_usdc > 0:
            return (self.total_profit_usdc / self.total_volume_usdc) * 100
        return 0.0


@dataclass
class BigWin:
    """A single trade event that qualifies as a big win."""

    wallet: str
    display_name: str
    market_question: str
    outcome: str
    profit_usdc: float
    roi_pct: float
    trade_size_usdc: float
    timestamp: int
    market_id: str = ""
    trade_id: str = ""
    end_date: str = ""
    avg_price: float = 0.0
    win_rate_30d: float = 0.0   # 30-day win rate
    win_rate: float = 0.0    # lifetime win rate
    win_streak: int = 0      # consecutive wins (most recent first)


@dataclass
class LeaderboardEntry:
    """Raw entry from the Polymarket /v1/leaderboard endpoint."""

    rank: int
    name: str
    proxy_wallet: str
    profit_usdc: float
    volume_usdc: float
    trades: int


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
    # Leaderboard metrics
    lifetime_pnl: float = 0.0
    lifetime_wr: float = 0.0
    wr_30d: float = 0.0
    pnl_30d: float = 0.0
    wins: int = 0
    losses: int = 0
    avg_roi: float = 0.0
    best_roi_trade: float = 0.0
    streak_current: int = 0
    streak_best: int = 0
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


@dataclass
class InternalWhaleRecord:
    wallet: str
    display_name: str = ""
    lifetime_pnl: float = 0.0
    lifetime_wr: float = 0.0
    wr_30d: float = 0.0
    pnl_30d: float = 0.0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    avg_roi: float = 0.0
    best_roi_trade: float = 0.0
    streak_current: int = 0
    streak_best: int = 0
    last_seen: str = ""
    updated_at: str = ""
    is_active: int = 1
    record_source: str = "wallet_tracker.db"
    categories_json: str = "[]"
