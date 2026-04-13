"""
Data models used throughout WhaleTrax.
Pure dataclasses – no external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


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


@dataclass
class LeaderboardEntry:
    """Raw entry from the Polymarket /v1/leaderboard endpoint."""

    rank: int
    name: str
    proxy_wallet: str
    profit_usdc: float
    volume_usdc: float
    trades: int
