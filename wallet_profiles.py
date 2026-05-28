#!/usr/bin/env python3
"""
Wallet Profile Manager — Polyshark
Maintains per-wallet cumulative statistics backed by complete position history.
All time-window win rates are RECALCULATED from _pos_history on every update.
This ensures accurate windows (30d/90d/6m/lifetime) from day 1 of tracking,
with no double-counting when a wallet is scanned multiple times.
"""
import json, datetime as dt
from pathlib import Path
from typing import Optional

PROFILE_FILE = Path('/tmp/wallet_profiles.json')
VAULT_DIR    = Path('/home/ubuntu/.openclaw/workspace/ompa_vault/brain/polyshark/whales')

class WalletProfile:
    """
    Cumulative wallet statistics backed by complete position history.

    All time-window win rates are RECALCULATED from _pos_history on every update.
    This ensures accurate windows (30d/90d/6m/lifetime) from day 1 of tracking,
    with no double-counting when a wallet is scanned multiple times.
    """

    def __init__(self, wallet: str, name: str = ''):
        self.wallet          = wallet
        self.name            = name
        self._pos_history: list[dict] = []   # complete position list, deduped
        self._seen_ids: set[str]            = set()   # dedupe by trade_id
        # Cached aggregates (recalculated from _pos_history)
        self._cache_valid   = False
        self._total_positions = 0
        self._total_wins     = 0
        self._losses         = 0
        self._positions_30d  = 0
        self._wins_30d       = 0
        self._pnl_30d        = 0.0
        self._positions_90d  = 0
        self._wins_90d       = 0
        self._positions_6m   = 0
        self._wins_6m        = 0
        self._current_streak = 0
        self._longest_streak = 0
        self._total_pnl      = 0.0
        self._avg_roi         = 0.0
        self._last_seen_ts   = 0
        # Meta
        self.first_seen      = dt.datetime.now(dt.timezone.utc).isoformat()
        self.updated_at      = dt.datetime.now(dt.timezone.utc).isoformat()

    # ── Properties (always recalculated from _pos_history) ──────────────

    @property
    def total_positions(self) -> int:
        self._recalc_if_needed()
        return self._total_positions

    @property
    def total_wins(self) -> int:
        self._recalc_if_needed()
        return self._total_wins

    @property
    def losses(self) -> int:
        self._recalc_if_needed()
        return self._losses

    @property
    def win_rate(self) -> float:
        if self._total_positions == 0:
            return 0.0
        return self._total_wins / self._total_positions * 100

    @property
    def win_rate_30d(self) -> float:
        self._recalc_if_needed()
        if self._positions_30d == 0:
            return 0.0
        return self._wins_30d / self._positions_30d * 100

    @property
    def win_rate_90d(self) -> float:
        self._recalc_if_needed()
        if self._positions_90d == 0:
            return 0.0
        return self._wins_90d / self._positions_90d * 100

    @property
    def win_rate_6m(self) -> float:
        self._recalc_if_needed()
        if self._positions_6m == 0:
            return 0.0
        return self._wins_6m / self._positions_6m * 100

    @property
    def current_streak(self) -> int:
        self._recalc_if_needed()
        return self._current_streak

    @property
    def longest_streak(self) -> int:
        self._recalc_if_needed()
        return self._longest_streak

    @property
    def total_pnl(self) -> float:
        self._recalc_if_needed()
        return self._total_pnl

    @property
    def avg_roi(self) -> float:
        self._recalc_if_needed()
        return self._avg_roi

    @property
    def pnl_30d(self) -> float:
        self._recalc_if_needed()
        return self._pnl_30d

    @property
    def last_seen_ts(self) -> int:
        self._recalc_if_needed()
        return self._last_seen_ts

    # ── Core: merge positions and recalculate all windows ────────────────

    def merge_positions(self, positions: list[dict]):
        """
        Merge a list of Polymarket positions into this profile's history.
        Deduplicates by trade_id (or timestamp+size as fallback).
        Then RECALCULATES all windows from the complete merged history.
        This is the key difference from update_with_position — we recalculate
        from full history, so multiple scans don't double-count.
        """
        now_ts = int(dt.datetime.now(dt.timezone.utc).timestamp())
        cutoff_30d = now_ts - 30  * 86400
        cutoff_90d = now_ts - 90  * 86400
        cutoff_6m  = now_ts - 180 * 86400

        for p in positions:
            trade_id = p.get('id') or p.get('trade_id') or ''
            key = trade_id or f"{p.get('timestamp','')}-{p.get('size','')}"
            if key and key in self._seen_ids:
                continue   # already have this position
            if key:
                self._seen_ids.add(key)

            pnl     = float(
                p.get('realizedPnl')
                or p.get('pnl')
                or p.get('profit')
                or p.get('profitAndLoss')
                or 0
            )
            roi_pct = float(
                p.get('roiPct')
                or p.get('roi')
                or 0
            )
            ts      = int(float(
                p.get('timestamp')
                or p.get('createdAt')
                or p.get('closedAt')
                or p.get('settledAt')
                or 0
            ))
            sz      = float(
                p.get('size')
                or p.get('totalBought')
                or p.get('amount')
                or p.get('cost')
                or 0
            )

            if not ts:
                ts = int(dt.datetime.now(dt.timezone.utc).timestamp())
            if not sz:
                sz = float(p.get('totalBought') or p.get('amount') or p.get('cost') or 0)
            if not sz:
                sz = 1.0

            self._pos_history.append({'pnl': pnl, 'roi_pct': roi_pct, 'ts': ts, 'sz': sz})
            self._last_seen_ts = max(self._last_seen_ts, ts)

        # Keep history bounded (last 500 positions — enough for 6m+ coverage)
        self._pos_history = sorted(self._pos_history, key=lambda x: x['ts'], reverse=True)[:500]

        # Recalculate all aggregates from complete history
        self._recalculate()

    def _recalculate(self):
        """Recalculate ALL cached aggregates from _pos_history."""
        now_ts = int(dt.datetime.now(dt.timezone.utc).timestamp())
        cutoff_30d = now_ts - 30  * 86400
        cutoff_90d = now_ts - 90  * 86400
        cutoff_6m  = now_ts - 180 * 86400

        self._total_positions = len(self._pos_history)
        self._total_wins       = sum(1 for p in self._pos_history if p['pnl'] > 0)
        self._losses           = self._total_positions - self._total_wins
        self._total_pnl        = sum(p['pnl'] for p in self._pos_history)
        self._avg_roi          = round(sum(p['roi_pct'] for p in self._pos_history) / max(1, self._total_positions), 2)

        self._positions_30d = sum(1 for p in self._pos_history if p['ts'] >= cutoff_30d)
        self._wins_30d      = sum(1 for p in self._pos_history if p['ts'] >= cutoff_30d and p['pnl'] > 0)
        self._pnl_30d       = sum(p['pnl'] for p in self._pos_history if p['ts'] >= cutoff_30d)

        self._positions_90d = sum(1 for p in self._pos_history if p['ts'] >= cutoff_90d)
        self._wins_90d       = sum(1 for p in self._pos_history if p['ts'] >= cutoff_90d and p['pnl'] > 0)

        self._positions_6m  = sum(1 for p in self._pos_history if p['ts'] >= cutoff_6m)
        self._wins_6m        = sum(1 for p in self._pos_history if p['ts'] >= cutoff_6m and p['pnl'] > 0)

        # Streak: most recent first
        streak, longest = 0, 0
        for p in self._pos_history:
            if p['pnl'] > 0:
                streak += 1
                longest = max(longest, streak)
            else:
                streak = 0
        self._current_streak = streak
        self._longest_streak = longest

        self._cache_valid = True
        self.updated_at   = dt.datetime.now(dt.timezone.utc).isoformat()

    def _recalc_if_needed(self):
        if not self._cache_valid:
            self._recalculate()

    def to_dict(self) -> dict:
        self._recalc_if_needed()
        return {
            'wallet': self.wallet,
            'name': self.name,
            'total_positions': self._total_positions,
            'total_wins': self._total_wins,
            'losses': self._losses,
            'win_rate': round(self.win_rate, 1),
            'win_rate_30d': round(self.win_rate_30d, 1),
            'win_rate_90d': round(self.win_rate_90d, 1),
            'win_rate_6m': round(self.win_rate_6m, 1),
            'pnl_30d': round(self.pnl_30d, 2),
            'current_streak': self._current_streak,
            'longest_streak': self._longest_streak,
            'total_pnl': round(self._total_pnl, 2),
            'avg_roi': round(self._avg_roi, 2),
            'first_seen': self.first_seen,
            'last_seen_ts': self._last_seen_ts,
            'updated_at': self.updated_at,
            '_pos_history': self._pos_history[-200:],  # last 200 for persistence
            '_seen_ids': list(self._seen_ids),         # persist dedupe set
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'WalletProfile':
        p = cls(d.get('wallet', ''), d.get('name', ''))
        p._pos_history = d.get('_pos_history', [])
        p._seen_ids    = set(d.get('_seen_ids', []))
        p.first_seen   = d.get('first_seen', '')
        p._last_seen_ts = d.get('last_seen_ts', 0)
        p.updated_at   = d.get('updated_at', '')
        p._cache_valid       = False
        return p

# ── Global profile cache ───────────────────────────────────────────────────

_profiles: dict[str, WalletProfile] = {}
_last_load: Optional[float] = None
_CACHE_TTL = 60  # seconds before reloading from disk

def load_profiles() -> dict[str, WalletProfile]:
    """Load all wallet profiles from disk, with 60s cache."""
    global _profiles, _last_load
    import time
    now = time.time()
    if _profiles and _last_load and (now - _last_load) < _CACHE_TTL:
        return _profiles
    _profiles = {}
    if PROFILE_FILE.exists():
        try:
            raw = json.loads(PROFILE_FILE.read_text())
            for wallet, data in raw.items():
                _profiles[wallet.lower()] = WalletProfile.from_dict(data)
        except Exception:
            pass
    _last_load = now
    return _profiles

def save_profiles(profiles: dict[str, WalletProfile]):
    """Persist all profiles to disk + OMPA."""
    global _last_load
    import time
    data = {wallet: p.to_dict() for wallet, p in profiles.items()}
    PROFILE_FILE.write_text(json.dumps(data, indent=2))
    _last_load = time.time()
    # Also write individual OMPA files
    for wallet, p in profiles.items():
        _write_ompa_profile(p)

def get_profile(wallet: str) -> WalletProfile:
    """Get or create a wallet profile."""
    profiles = load_profiles()
    wallet = wallet.lower()
    if wallet not in profiles:
        profiles[wallet] = WalletProfile(wallet)
    return profiles[wallet]

def update_profile(wallet: str, name: str, positions: list[dict]):
    """
    Update a wallet's profile with a batch of positions.
    Merges (dedupes) and then recalculates ALL windows from the complete history.
    """
    profiles = load_profiles()
    wallet = wallet.lower()
    if wallet not in profiles:
        profiles[wallet] = WalletProfile(wallet)
    p = profiles[wallet]
    p.name = name or p.name
    p.merge_positions(positions)  # dedupes + full recalc
    save_profiles(profiles)
    return p

def _write_ompa_profile(p: WalletProfile):
    """Write a wallet profile to OMPA brain."""
    vault = Path('/home/ubuntu/.openclaw/workspace/ompa_vault/brain/polyshark/whales')
    vault.mkdir(parents=True, exist_ok=True)
    safe = p.wallet.lower().replace('0x', '')[:16]
    path = vault / f"{safe}.md"
    text = f"""---
type: whale_profile
wallet: {p.wallet}
updated: {p.updated_at}
total_positions: {p.total_positions}
total_wins: {p.total_wins}
losses: {p.losses}
win_rate: {p.win_rate:.1f}
win_rate_30d: {p.win_rate_30d:.1f}
win_rate_90d: {p.win_rate_90d:.1f}
win_rate_6m: {p.win_rate_6m:.1f}
current_streak: {p.current_streak}
longest_streak: {p.longest_streak}
total_pnl: {p.total_pnl:.2f}
avg_roi: {p.avg_roi:.2f}
first_seen: {p.first_seen}
last_seen_ts: {p.last_seen_ts}
---

# Whale Profile — {p.name or p.wallet[:12]}

**Wallet:** `{p.wallet}`
**Display Name:** {p.name}
**Total Positions:** {p.total_positions}
**Wins:** {p.total_wins} | **Losses:** {p.losses}
**Lifetime Win Rate:** {p.win_rate:.1f}%
**30-Day Win Rate:** {p.win_rate_30d:.1f}%
**90-Day Win Rate:** {p.win_rate_90d:.1f}%
**6-Month Win Rate:** {p.win_rate_6m:.1f}%
**Current Streak:** {p.current_streak} | **Longest Streak:** {p.longest_streak}
**Total PnL:** ${p.total_pnl:,.2f}
**Avg ROI:** {p.avg_roi:.1f}%
**First Seen:** {p.first_seen}
**Last Updated:** {p.updated_at}
"""
    path.write_text(text)
