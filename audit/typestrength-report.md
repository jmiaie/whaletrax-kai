# WhaleTrax Type Strength Assessment Report

This report identifies weak type hints (Any, bare list/dict/tuple, untyped signatures) in the WhaleTrax repository and proposes stronger alternatives.

## Weak Type Locations & Assessment

### 1. `src/polymarket_client.py`

| Location | Weak Type | Context / Actual Data | Proposed Strong Type |
| :--- | :--- | :--- | :--- |
| `_get(..., params: Optional[dict])` | `dict` | HTTP query parameters (key-value pairs) | `dict[str, Any]` |
| `_get(...) -> Any` | `Any` | Parsed JSON response (dict, list, or None) | `dict[str, Any] \| list[dict[str, Any]] \| None` |
| `_paginate(..., params: dict)` | `dict` | HTTP query parameters | `dict[str, Any]` |
| `_paginate(...) -> list[dict]` | `list[dict]` | List of parsed JSON objects | `list[dict[str, Any]]` |
| `get_markets(...) -> list[dict]` | `list[dict]` | List of market metadata objects | `list[dict[str, Any]]` |
| `get_market(...) -> Optional[dict]` | `dict` | Market metadata object | `dict[str, Any]` |
| `get_events(...) -> list[dict]` | `list[dict]` | List of event metadata objects | `list[dict[str, Any]]` |
| `get_leaderboard(...) -> list[dict]` | `list[dict]` | List of leaderboard entries | `list[dict[str, Any]]` |
| `get_user_trades(...) -> list[dict]` | `list[dict]` | List of trade objects | `list[dict[str, Any]]` |
| `get_user_positions(...) -> list[dict]` | `list[dict]` | List of position objects | `list[dict[str, Any]]` |
| `get_user_closed_positions(...) -> list[dict]` | `list[dict]` | List of closed position objects | `list[dict[str, Any]]` |
| `get_user_value(...) -> Optional[dict]` | `dict` | Portfolio value summary object | `dict[str, Any]` |
| `get_user_activity(...) -> list[dict]` | `list[dict]` | List of activity objects | `list[dict[str, Any]]` |
| `get_market_holders(...) -> list[dict]` | `list[dict]` | List of holder objects | `list[dict[str, Any]]` |
| `get_clob_market_trades(...) -> list[dict]` | `list[dict]` | List of CLOB trade objects | `list[dict[str, Any]]` |
| `get_order_book(...) -> Optional[dict]` | `dict` | Order book object | `dict[str, Any]` |

**Note on `Any`**: In `polymarket_client.py`, `Any` is used for raw API responses which are deeply nested and vary by endpoint. Using `dict[str, Any]` or `list[dict[str, Any]]` is the appropriate strengthening here without introducing complex TypedDicts for external API shapes that might change.

### 2. `src/big_win_detector.py`

| Location | Weak Type | Context / Actual Data | Proposed Strong Type |
| :--- | :--- | :--- | :--- |
| `_closed_position_to_big_win(raw: dict, ...)` | `dict` | Raw API closed-position object | `dict[str, Any]` |
| `_leaderboard_wallet_to_big_wins(entry_raw: dict, ...)` | `dict` | Raw API leaderboard entry | `dict[str, Any]` |

### 3. `src/wallethound/deposit_tracker.py`

| Location | Weak Type | Context / Actual Data | Proposed Strong Type |
| :--- | :--- | :--- | :--- |
| `_classify_activity(raw: dict)` | `dict` | Raw API activity record | `dict[str, Any]` |
| `build_balance_snapshots(..., closed_positions: list[dict], ...)` | `list[dict]` | List of raw API closed-position objects | `list[dict[str, Any]]` |

### 4. `src/display.py`

| Location | Weak Type | Context / Actual Data | Proposed Strong Type |
| :--- | :--- | :--- | :--- |
| `show_market_holders(holders: list[dict], ...)` | `list[dict]` | List of holder objects | `list[dict[str, Any]]` |

### 5. `main.py`

| Location | Weak Type | Context / Actual Data | Proposed Strong Type |
| :--- | :--- | :--- | :--- |
| `scan_market_cmd(...) -> market_big_wins: list` | `list` | List of big wins for a market | `list[BigWin]` |

### 6. `src/parsers.py`

| Location | Weak Type | Context / Actual Data | Proposed Strong Type |
| :--- | :--- | :--- | :--- |
| `parse_leaderboard_entry(raw: dict, ...)` | `dict` | Raw API leaderboard entry | `dict[str, Any]` |
| `parse_trade(raw: dict, ...)` | `dict` | Raw API trade object | `dict[str, Any]` |
| `parse_position(raw: dict, ...)` | `dict` | Raw API position object | `dict[str, Any]` |

### 7. `src/wallet_scanner.py`

| Location | Weak Type | Context / Actual Data | Proposed Strong Type |
| :--- | :--- | :--- | :--- |
| `_enrich_stats_from_closed_positions(..., positions: list[dict])` | `list[dict]` | List of raw API closed-position objects | `list[dict[str, Any]]` |

1.  Update `src/polymarket_client.py` to use `dict[str, Any]` and `list[dict[str, Any]]`.
2.  Update `src/big_win_detector.py` to use `dict[str, Any]`.
3.  Update `src/wallethound/deposit_tracker.py` to use `dict[str, Any]` and `list[dict[str, Any]]`.
4.  Update `src/display.py` to use `list[dict[str, Any]]`.
5.  Update `main.py` to use `list[BigWin]`.
6.  Verify by running `python3 -m py_compile` on each modified file.
