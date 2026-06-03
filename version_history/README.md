# WhaleTrax / Polyshark Version History

**Goal:** Track all significant code changes so we can roll back if something breaks.
**Location:** `repos/whaletrax/version_history/`

## Versioning Conventions
- Format: `vYYYY-MM-DD.N` (date + increment)
- Each entry: what changed, why, what files, how to rollback
- Copy of pre-change file stored in `version_history/{version}/` folder

---

## v2026-06-02.1 — Initial Session Baseline
**Time:** 2026-06-02 ~03:00 UTC
**Status:** PRE-CHANGES (baseline reference)
**Files:** All files at start of session — no changes yet

---

## v2026-06-02.2 — Early Exit Forensic Audit
**Time:** 2026-06-02 ~04:30 UTC
**What:** Forensic audit detecting partial close / early exit behavior in whale wallets
**Files Changed:**
- `repos/ompa_vault/brain/polyshark/early_exit_audit_2026-06-02.md` — **NEW**

**Finding:** ZERO evidence of early exits in 100% WR wallets. 251 opposite-sign events found — all in mixed-WR wallets (normal losses). No rollback needed, purely additive.

---

## v2026-06-02.3 — 30D Stats Card Bug Fix
**Time:** 2026-06-02 ~05:00 UTC
**What:** Cards with `win_rate_30d > 0` but `roi_30d = 0` were skipping the entire 30D section
**Root Cause:** `if roi_30d != 0:` — only showed 30D block when ROI had a value
**Fix:** Changed to `if win_rate_30d > 0 or roi_30d != 0:` in all card functions

**Files Changed:**
- `alerts/polyshark_alert.py` — lines ~67, ~282, ~446 (3 card variants)
  - Before: `if roi_30d != 0:`
  - After: `if win_rate_30d > 0 or roi_30d != 0:`

**Rollback:** Change all 3 occurrences back to `if roi_30d != 0:` in `alerts/polyshark_alert.py`

---

## v2026-06-02.4 — Partial Close Detector (NEW FILE)
**Time:** 2026-06-02 ~05:15 UTC
**What:** New daemon monitors position size changes to detect early exits / partial closes
**Files Added:**
- `partial_close_detector.py` — main daemon
- `partial_close_detector.db` — own SQLite DB (no lock conflict with wallet_tracker)

**Key Features:**
- Polls `get_user_positions` every 5 min for all active wallets
- Stores `position_latest` + `position_snapshots` (history)
- Flags shrink ≥5% before `endDate` → `partial_close_events` table
- Resolution pass: cross-refs with `get_user_closed_positions` for realized P&L

**Run:** `nohup python3 partial_close_detector.py > logs/partial_close_detector.log 2>&1 &`

**Rollback:** Delete the file and `partial_close_detector.db` if needed
```bash
pkill -f partial_close_detector.py
rm repos/whaletrax/partial_close_detector.py
rm repos/whaletrax/partial_close_detector.db
```

---

## v2026-06-02.5 — Geo-Availability Detection & Card Badge
**Time:** 2026-06-02 ~05:45 UTC
**What:** Added geo-restriction tagging to all cards and the alert pipeline

**Files Changed:**
- `polyshark_router.py` — added `detect_geo_availability()` function + `geo_available` in alert dict and queue
- `alerts/polyshark_alert.py` — `geo_available` param added to all 4 card functions + geo badge in footer (3 card variants)
- `live_scanner.py` — `geo_available` passed to `make_trade_alert_card` in both test and live paths
- `card_stats.py` — `geo_available` TEXT column added to `cards` table

**Classification Logic:**
| Category | Result |
|---|---|
| Crypto/NFT/DeFi keywords | `NON_US_ONLY` |
| Stock/Econ keywords (inflation, fed, gdp, etc.) | `NON_US_ONLY` |
| Sports/Esports | `GLOBAL` |
| Elections/Politics | `GLOBAL` |
| Everything else | `UNKNOWN` (silent) |

**Card Badge:**
- 🌍 `Global` (green) — available everywhere
- 🇺🇸 `US Only` (blue) — geo-restricted

**Rollback for router:**
```bash
# Kill router
pkill -f polyshark_router.py
# Remove new function from polyshark_router.py — delete detect_geo_availability() (~lines 323-365)
# Remove 'geo_available' from bw_dict and queue dict
# Restart
cd repos/whaletrax && nohup python3 polyshark_router.py >> logs/polyshark_router.log 2>&1 &
```

**Rollback for card_stats:**
```bash
# Add back is_curated column if needed — the geo_available column is ADDITIVE (safe)
# No rollback needed — new column only adds data, doesn't change existing schema
```

---

## v2026-06-02.9 — Geo Tag Moved Into Header, Bracket Replaced with [Polyshark PRO]
**Time:** 2026-06-02 ~07:00 UTC
**What:** Changed `[{tier.upper()}]` → `[Polyshark PRO{geo_suffix}]` and moved geo emoji inside the bracket next to PRO. Footer geo tag removed (now redundant).
**Result:**
- `GLOBAL` → `🟢 [Polyshark PRO 🌍] 🏅`
- `NON_US_ONLY` → `🟢 [Polyshark PRO 🇺🇸] 🏅`
- `UNKNOWN` → `🟢 [Polyshark PRO] 🏅`
**Files Changed:** `polyshark_router.py`
**Snapshot:** `version_history/v2026-06-02.9/`
**Rollback:**
```bash
cp version_history/v2026-06-02.9/polyshark_router.py polyshark_router.py
pkill -f polyshark_router.py && sleep 3 && nohup python3 polyshark_router.py >> logs/polyshark_router.log 2>&1 &
```

## v2026-06-02.8 — Fix geo_available Not Attached to bw Before format_card
**Time:** 2026-06-02 ~06:56 UTC
**What:** `geo_available` was in the queue dict but never attached to the `bw` BigWin object before `format_card()` was called — so the geo tag was missing from all text captions.
**Fix:** Added `bw.geo_available = item.get('geo_available', 'UNKNOWN')` before the `format_card()` call at line ~602.
**Files Changed:** `polyshark_router.py`
**Snapshot:** `version_history/v2026-06-02.7/` (pre-fix backup)
**Rollback:**
```bash
cp version_history/v2026-06-02.7/polyshark_router.py polyshark_router.py
pkill -f polyshark_router.py && sleep 3 && nohup python3 polyshark_router.py >> logs/polyshark_router.log 2>&1 &
```

## v2026-06-02.7 — Geo Badge Added to Text Captions
**Time:** 2026-06-02 ~06:42 UTC
**What:** Geo tags were missing from text captions (only appeared on PNG cards). Added to `format_card()` in router.
**Files Changed:**
- `polyshark_router.py` — `format_card()` now appends geo badge after trader line
  - `GLOBAL` → `Global`
  - `NON_US_ONLY` → 🇺🇸 `US Only`
  - `UNKNOWN` → silent (no tag)
**Snapshot:** `version_history/v2026-06-02.6a/` (pre-change backup)
**Rollback:**
```bash
cp version_history/v2026-06-02.6a/polyshark_router.py polyshark_router.py
pkill -f polyshark_router.py && sleep 3 && nohup python3 polyshark_router.py >> logs/polyshark_router.log 2>&1 &
```

## v2026-06-02.6 — Router Restart with Geo Active
**Time:** 2026-06-02 ~06:22 UTC
**What:** Restarted `polyshark_router.py` with geo detection code live
**PID:** 306903
**Status:** Killed and restarted at .7
**Snapshot saved:** `version_history/v2026-06-02.6/`

---

## Rollback Quick Reference

| Version | What Changed | How to Roll Back |
|---|---|---|
| `.3` — 30D bug fix | `if roi_30d != 0:` → `if win_rate_30d > 0 or` | Revert in `alerts/polyshark_alert.py` |
| `.4` — partial close detector | New file + new DB | `pkill` + delete file + delete `partial_close_detector.db` |
| `.5` — geo tagging | Added function + params + badge + DB column | Remove `detect_geo_availability()` from router, remove `geo_available` from dicts/cards, DB column is safe to leave |
| `.6` — router restart | Already running | Just restart router again with old code |

---

## How to Snapshot Before Making Changes

```bash
cd /home/ubuntu/.openclaw/workspace/repos/whaletrax
VER="v2026-06-02.7"
mkdir -p version_history/$VER
cp polyshark_router.py version_history/$VER/
cp alerts/polyshark_alert.py version_history/$VER/
cp card_stats.py version_history/$VER/
cp live_scanner.py version_history/$VER/
echo "$VER snapshot saved at $(date -Iseconds)"
```

Then make changes. If something breaks, copy back from the version folder.

---

*Last updated: 2026-06-02 06:25 UTC*
## v2026-06-02.10 — Tiered Position Sizing + Multi-Position Strategy
**Time:** 2026-06-02 ~12:15 UTC
**What:** Replaced flat position caps with tiered system. Added multi-position strategy (Top-3 at 25% total). Realistic model based on actual on-chain whale trade data.
**Key Files:** `top1_strategy.py`, `top2_strategy.py`, `fast_scan.py`, `position_sizer.py` (NEW)
**Tiered Caps (per position, scales with balance):**
- $0–$5K balance → $500/position
- $5K–$20K → $1,000/position
- $20K–$50K → $2,500/position
- $50K–$200K → $5,000/position
- $200K+ → $10,000/position
**Recommended Strategy:** $2K start | 25% total fraction | Top-3 plays/day | Realistic May end: $1,058,601
**Snapshot:** `version_history/v2026-06-02.9/`
**Rollback:** `cp version_history/v2026-06-02.9/polyshark_router.py polyshark_router.py`

---

## v2026-06-02.11 — Card Format Locked + New Wallet Consolidation
**Time:** 2026-06-02 ~17:10 UTC
**What:** Card format finalized. New wallet (≤30d) stat consolidation. Bug fixes. Top-20 analysis DB + CSV built.

**Card Header:** `🟢 🦈 [Polyshark PRO 🌍] 🦈🟢`
**Card Footer:** `🌊 [0x0380...1073d](...) 🐋`
**Market Line:** `❓ <question>`

**New Wallet Rule:**
- Wallets ≤30 days old: single consolidated stat line `🏅 100% (200/200) WR | 💰 +$1,060,416 P/L`
- Older wallets: retains 30Day + Lifetime split

**Bug Fixes:**
- `inverse_candidate` NameError → moved definition before first use in format_card()
- Router had duplicate PID 312532 (old instance) → killed

**New Assets:**
- `repos/whaletrax/top_wallets.db` — 20 wallets, 2,200 positions (SQLite)
- `repos/whaletrax/top20_wallets.csv` — Full spreadsheet, all 19 metrics
- `repos/whaletrax/POLYSHARK_BOT_SPEC.md` — Complete system specification
- `repos/whaletrax/top20_analysis.py` — DB builder script

**Top-20 Wallet Highlights:**
| Rank | Wallet | Total PnL | Avg Mult | Std Dev | Risk |
|------|--------|-----------|---------|---------|------|
| 1 | 0x4924...3782 | $49.8M | 0.4854 | 0.0352 | LOW |
| 2 | 0x2a2c...9bc1 | $20.0M | 0.4222 | 0.1303 | MEDIUM |
| 4 | 0x6a72...033e | $16.9M | 0.5163 | 0.0911 | LOW |
| 6 | 0xa5ea...896a | $15.3M | 0.5540 | 0.0885 | LOW |
| 7 | 0x8457...887fd | $14.1M | 0.7807 | 0.2043 | MEDIUM |
| 19 | 0x805a...835 | $6.7M | **0.8526** | 0.1976 | MEDIUM |

**Snapshot:** `version_history/v2026-06-02.11/`
**Rollback:** `cp version_history/v2026-06-02.11/polyshark_router.py polyshark_router.py`

---

*Last updated: 2026-06-02 17:15 UTC*

---

## v2026-06-02.12 — Execution Gateway Directive Received
**Time:** 2026-06-02 ~17:47 UTC
**Status:** CHECKPOINT SET — execution pending

**What:** Polymarket US copy-trading execution directive received from Jeff.
- `polymarket-us` library needs installation
- API credentials (POLYMARKET_KEY_ID + POLYMARKET_SECRET_KEY) needed before execution
- Skill module: `~/.openclaw/workspace/skills/polyshark/SKILL.md`
- `DEPLOYMENT_DIRECTIVE.md` saved to whaletrax and snapshot folder

**Files Snapshotted:**
- All v2026-06-02.11 files
- `DEPLOYMENT_DIRECTIVE.md`
- `POLYSHARK_BOT_SPEC.md`
- `AUDIT_2026-06-02.md`

**Snapshot:** `version_history/v2026-06-02.12/`
**Rollback:** `cp version_history/v2026-06-02.12/polyshark_router.py polyshark_router.py`

---

*Last updated: 2026-06-02 17:47 UTC*
