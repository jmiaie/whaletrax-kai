# Whaletrax Type Consolidation Assessment

## Type Definitions Found

### File: `src/models.py`
- `Trade`: Represents a single resolved/closed trade.
- `Position`: Represents an open or closed position.
- `WalletStats`: Aggregated statistics for a single wallet address.
- `BigWin`: A single trade event that qualifies as a big win.
- `LeaderboardEntry`: Raw entry from the Polymarket /v1/leaderboard endpoint.

### File: `src/wallethound/models.py`
- `WalletTier`: Classification tier for a tracked wallet (Enum).
- `DepositWithdrawal`: A single deposit or withdrawal event.
- `BalanceSnapshot`: Point-in-time balance snapshot for a wallet.
- `ConsistencyScore`: Metrics that measure how consistently a wallet wins.
- `GrowthMetrics`: Metrics for wallet balance growth / compounding analysis.
- `HoundResult`: A single wallet result from WalletHound scanning.

## Duplicates and Drift Assessment

- **No direct class name collisions**: The types are logically separated between core data models and WalletHound-specific metrics.
- **Overlap in Purpose**: `WalletStats` (in `src/models.py`) and `HoundResult` (in `src/wallethound/models.py`) both aggregate wallet-level statistics. 
    - `WalletStats` is more basic (profit, volume, trades).
    - `HoundResult` is much more comprehensive, including `WalletStats` data (profit, volume, trades, win rate) plus extra fields for consistency and compounding.
- **Internal Consistency**: `HoundResult` actually re-implements many fields found in `WalletStats` rather than embedding or inheriting from it.

## Consolidation Plan

1. **Move `WalletTier`** to `src/models.py` as it's a useful global classification.
2. **Move WalletHound-specific models** to `src/models.py` or keep them in `src/wallethound/models.py`? 
    - Given the task is "Type Consolidation", moving everything into a single source of truth (`src/models.py`) is cleaner for a small repo like this.
3. **Refactor `HoundResult`** to potentially include or inherit from `WalletStats` to reduce duplication of fields like `total_profit_usdc`, `total_volume_usdc`, etc.

## Decisions
- Consolidate all types into `src/models.py`.
- Update imports across the codebase.

## Consolidation Results (2026-04-25)

- Moved all `WalletHound` specific models from `src/wallethound/models.py` to `src/models.py`.
- Moved `WalletTier` enum to `src/models.py`.
- Updated all internal imports in `src/wallethound/` to point to `..models` (unified source of truth).
- `src/wallethound/models.py` now serves as a deprecated redirect/proxy.
- Verified compilation of all modified files.
