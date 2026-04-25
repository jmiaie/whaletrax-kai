# Slopp Report — WhaleTrax

**Audit date:** 2026-04-25
**Scope:** `src/` + `wallethound_web/` Python files
**Scanner:** SUBAGENT 7 (deprecated code + AI slop)

---

## Summary

| Category | Count | Remove? |
|---|---|---|
| Deprecated / Legacy | 1 | ✅ Yes |
| AI-generated slop (comments) | 2 | ✅ Rewrite |
| Stub `pass` functions | 0 | — |
| Version-gated logic | 0 | — |
| TODO / FIXME / HACK | 0 | — |
| Empty try blocks | 0 | — |
| Edit-history comments | 0 | — |

**Overall assessment:** The codebase is clean. One deprecated redirect module and two redundant/low-value comments are the only findings.

---

## Finding 1 — `src/wallethound/models.py` (DEPRECATED MODULE)

**File:** `src/wallethound/models.py`
**Classification:** Deprecated / Legacy
**Confidence:** 🔴 HIGH

### Description

The entire file is a deprecated redirect. Its docstring explicitly says:

```
(DEPRECATED) All models moved to src/models.py
```

It re-exports everything from `src.models`:

```python
from ..models import (
    WalletTier,
    DepositWithdrawal,
    BalanceSnapshot,
    ConsistencyScore,
    GrowthMetrics,
    HoundResult
)
```

### Why it's deprecated

The `src/models.py` module holds the canonical definitions. `src/wallethound/models.py` was left as a proxy so existing imports wouldn't break, but it should be removed and callers updated.

### Active imports of this module

| File | Symbols imported |
|---|---|
| `main.py:35` | `WalletTier` |
| `main.py:330` | `ConsistencyScore` |
| `main.py:384` | `GrowthMetrics` |
| `wallethound_web/app.py:30` | `WalletTier, ConsistencyScore, GrowthMetrics, HoundResult` |
| `wallethound/scanner.py` | `DepositWithdrawal, BalanceSnapshot` (via `from .deposit_tracker import`) |

### Action: REMOVE this file. Update importers to use `src.models`.

---

## Finding 2 — `src/wallet_scanner.py:180` (REDUNDANT COMMENT)

**File:** `src/wallet_scanner.py`, line 180
**Classification:** AI slop (low-value comment)
**Confidence:** 🟡 MEDIUM

### Original

```python
# Unknown or empty side values are treated as opening legs as a best-effort
# fallback (they cannot be matched to a known closing event).
```

### Problem

The function's docstring (lines 155–166) already explains this fully. This comment is word-for-word what the code does — it narrates the implementation, not the intent. It reads like an AI regenerated the docstring and left a redundant version of it inline.

### Action: REMOVE the comment. The docstring already covers this.

---

## Finding 3 — `src/parsers.py:14` (LOW-VALUE COMMENT)

**File:** `src/parsers.py`, line 14
**Classification:** AI slop (low-value)
**Confidence:** 🟡 MEDIUM

### Original

```python
# Some API versions wrap under "positions"
```

### Problem

Comments explaining raw API behavior (WHAT) without context on WHY the wrapping matters are low-value. An engineer seeing this comment still doesn't know *when* this matters, *why* Polymarket changed this, or *what problem it solves*.

### Action: REWRITE to explain the intent:

```python
# The closed-positions endpoint has changed its response envelope over time.
# Wrap the list under "positions" when the raw response is a list containing
# a dict with a "positions" key — this covers both old and current API shapes.
```

---

## Changes Made

1. **Removed** `src/wallethound/models.py`
2. **Updated** `main.py` — import `WalletTier, ConsistencyScore, GrowthMetrics` from `src.models`
3. **Updated** `wallethound_web/app.py` — import those symbols from `src.models`
4. **Removed** redundant comment in `src/wallet_scanner.py:180`
5. **Rewrote** low-value comment in `src/parsers.py:14`

---

## Files Not Modified (No Action Needed)

- `requirements.txt` — no deprecated packages
- `src/config.py` — all constants actively used by CLI defaults and runtime config
- `src/wallethound/deposit_tracker.py` — `compute_organic_growth` docstring is legitimate explanation of accounting model (explains WHY the formula is correct)
- `src/big_win_detector.py:124-127` — multiple key fallbacks for API field name variance are intentional, not deprecated fallback logic
