# Circular Import Assessment - Whaletrax

## Identified Cycles

### Cycle 1: `src.wallethound.scanner` ↔ `src.wallethound.compounders`
- **Chain:** `scanner.py` imports `compounders`, and `compounders.py` imports `scanner` (indirectly via `_safe_float` from `..wallet_scanner`).
- **Actually:** `compounders.py` imports `..wallet_scanner` which is fine. However, `scanner.py` imports `compounders`. 
- **Re-checking imports:**
    - `src/wallethound/scanner.py` imports `from . import compounders, consistent_winners`.
    - `src/wallethound/compounders.py` imports `from ..wallet_scanner import _safe_float`.
    - `src/wallet_scanner.py` does NOT import `scanner.py`.
- **Verdict:** No cycle here.

### Cycle 2: `src.big_win_detector` ↔ `src.wallet_scanner`
- **Chain:** `big_win_detector.py` imports `_parse_leaderboard_entry` and `_safe_float` from `.wallet_scanner`.
- **`wallet_scanner.py`** does NOT import `big_win_detector`.
- **Verdict:** No cycle here.

### Cycle 3: `src.wallethound.scanner` ↔ `src.big_win_detector`
- **Chain:** `scanner.py` imports `scan_big_wins_for_wallet` from `..big_win_detector`.
- **`big_win_detector.py`** imports `_parse_leaderboard_entry` and `_safe_float` from `.wallet_scanner`.
- **Verdict:** No cycle here.

## Detailed Analysis

I have manually mapped the imports for the core modules:

| Module | Imports From |
| --- | --- |
| `src/models.py` | (none internal) |
| `src/config.py` | (none internal) |
| `src/polymarket_client.py` | `.config` |
| `src/wallet_scanner.py` | `.config`, `.polymarket_client`, `.models` |
| `src/big_win_detector.py` | `.config`, `.polymarket_client`, `.models`, `.wallet_scanner` |
| `src/display.py` | `.models` |
| `src/wallethound/models.py` | (none internal) |
| `src/wallethound/deposit_tracker.py` | `..polymarket_client`, `..wallet_scanner`, `.models` |
| `src/wallethound/consistent_winners.py` | `..polymarket_client`, `..wallet_scanner`, `.models` |
| `src/wallethound/compounders.py` | `..polymarket_client`, `..wallet_scanner`, `.deposit_tracker`, `.models` |
| `src/wallethound/scanner.py` | `..config`, `..polymarket_client`, `..big_win_detector`, `..wallet_scanner`, `.compounders`, `.consistent_winners`, `.deposit_tracker`, `.models` |
| `src/wallethound/display.py` | `..display`, `.models` |

### Potential Risks Found

1. **`src/wallet_scanner.py`** has a local import in `_compute_realised_pnl`:
   ```python
   def _compute_realised_pnl(trades: list[Trade]) -> list[Trade]:
       from collections import defaultdict
   ```
   This is not a circular import, just a local import for performance/scope.

2. **`main.py`** and **`wallethound_web/app.py`** import almost everything, but since they are entry points, they don't cause cycles unless they are imported by the modules they import (which they aren't).

## Conclusion

**No circular dependencies found.** The project structure uses a clean hierarchical dependency tree:
`models` -> `client` -> `scanners` -> `detectors` -> `hound` -> `main/app`.

Sub-modules in `wallethound` depend on the base `src` modules and their own `models`, but they do not import each other in a way that circles back. `scanner.py` acts as the orchestrator for the `wallethound` package and is the only one importing the other sibling modules.

## Recommendations
- Keep `_safe_float` and other utility functions in a dedicated `src/utils.py` if they continue to be imported by many modules, to prevent the need for importing `wallet_scanner.py` just for a utility. Currently, `wallet_scanner.py` is serving as a "utils" provider for some functions, which is the most likely place a cycle would start if `wallet_scanner` ever needed to import one of those modules.
