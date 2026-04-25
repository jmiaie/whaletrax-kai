# Deprecated proxy — all WalletHound models moved to src/models.py
# Import from there to avoid drift. Kept for backward compat with any external code.
from ..models import (
    WalletTier, DepositWithdrawal, BalanceSnapshot,
    ConsistencyScore, GrowthMetrics, HoundResult
)

__all__ = ['WalletTier', 'DepositWithdrawal', 'BalanceSnapshot', 'ConsistencyScore', 'GrowthMetrics', 'HoundResult']