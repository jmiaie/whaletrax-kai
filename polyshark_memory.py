#!/usr/bin/env python3
"""
PolysharkMemory — OMPA brain-first memory for Polyshark alerts, faults, whales, markets.
Writes structured .md files to ompa_vault/brain/polyshark/* for semantic search.
"""
import sys, json, datetime as dt
from pathlib import Path

VAULT = Path('/home/ubuntu/.openclaw/workspace/ompa_vault/brain/polyshark')
FAULTS_FILE = Path('/tmp/polyshark_faults.json')
STATE_FILE  = Path('/tmp/polyshark_router_state.json')
QUEUE_FILE  = Path('/tmp/polyshark_router_queue.json')

def now():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

# ─── Alerts ────────────────────────────────────────────────────────────────────

def ingest_alert(bw_dict: dict, tier: str):
    """Write a whale win alert to brain/polyshark/alerts/."""
    market_id = bw_dict.get('market_id', 'unknown')[:16]
    ts = now().replace(' ', '_').replace(':', '')
    path = VAULT / 'alerts' / f"{ts}_{market_id}.md"
    text = f"""---
type: whale_alert
tier: {tier}
timestamp: {now()}
wallet: {bw_dict.get('wallet','')}
market_id: {bw_dict.get('market_id','')}
profit_usdc: {bw_dict.get('profit_usdc', 0)}
roi_pct: {bw_dict.get('roi_pct', 0)}
trade_size_usdc: {bw_dict.get('trade_size_usdc', 0)}
category: {bw_dict.get('cats', ['pro'])[0]}
win_rate_30d: {bw_dict.get('win_rate', 0)}
win_streak: {bw_dict.get('win_streak', 0)}
outcome: {bw_dict.get('outcome','')}
trade_date: {bw_dict.get('timestamp','')}
resolved_date: {bw_dict.get('end_date','')}
---

# Whale Alert — {tier.upper()}

**Wallet:** `{bw_dict.get('wallet','')}`
**Display Name:** {bw_dict.get('display_name', 'Anonymous Whale')}
**Market:** {bw_dict.get('question','')[:80]}

| Field | Value |
|-------|-------|
| Profit | ${bw_dict.get('profit_usdc', 0):,.0f} |
| ROI | {bw_dict.get('roi_pct', 0):.0f}% |
| Position Size | ${bw_dict.get('trade_size_usdc', 0):,.0f} |
| Entry Price | {float(bw_dict.get('avg_price', 0))*100:.1f}¢ |
| Outcome Bet | {bw_dict.get('outcome','')} |
| Category | {bw_dict.get('cats', ['pro'])[0]} |
| 30-Day Win Rate | {bw_dict.get('win_rate', 0):.0f}% |
| Win Streak | {bw_dict.get('win_streak', 0)} |
| Opened | {bw_dict.get('timestamp','')} |
| Resolved | {bw_dict.get('end_date','')} |

**Link:** https://polymarket.com/event/{bw_dict.get('market_id','')}
"""
    path.write_text(text)
    return path

# ─── Faults ───────────────────────────────────────────────────────────────────

def ingest_fault(kind: str, detail: str, extra: dict = None):
    """Append a fault entry to brain/polyshark/faults/ and to FAULTS_FILE."""
    ts = now().replace(' ', '_').replace(':', '')
    extra_str = json.dumps(extra) if extra else ''
    path = VAULT / 'faults' / f"{ts}_{kind}.md"
    text = f"""---
type: fault
kind: {kind}
timestamp: {now()}
detail: {detail}
{extra_str}
---

# Fault — {kind}

**Detail:** {detail}
**Extra:** {extra_str}
"""
    path.write_text(text)

    # Also append to fault log
    try:
        faults = json.loads(FAULTS_FILE.read_text()) if FAULTS_FILE.exists() else []
    except Exception:
        faults = []
    entry = {'ts': dt.datetime.now(dt.timezone.utc).isoformat(), 'kind': kind, 'detail': detail}
    if extra:
        entry.update(extra)
    faults.append(entry)
    faults = faults[-500:]
    FAULTS_FILE.write_text(json.dumps(faults, indent=2))

    return path

# ─── Whales ───────────────────────────────────────────────────────────────────

def ingest_whale_profile(profile_dict: dict):
    """Write a full wallet profile to brain/polyshark/whales/ (used by wallet_profiles)."""
    wallet = profile_dict.get('wallet', 'unknown')
    safe   = wallet.lower().replace('0x', '')[:16]
    path   = VAULT / 'whales' / f"{safe}_lifetime.md"
    text   = f"""---
type: whale_profile
wallet: {wallet}
updated: {profile_dict.get('updated_at','')}
total_positions: {profile_dict.get('total_positions',0)}
total_wins: {profile_dict.get('total_wins',0)}
losses: {profile_dict.get('losses',0)}
win_rate: {profile_dict.get('win_rate',0)}
win_rate_30d: {profile_dict.get('win_rate_30d',0)}
win_rate_90d: {profile_dict.get('win_rate_90d',0)}
win_rate_6m: {profile_dict.get('win_rate_6m',0)}
current_streak: {profile_dict.get('current_streak',0)}
longest_streak: {profile_dict.get('longest_streak',0)}
total_pnl: {profile_dict.get('total_pnl',0)}
avg_roi: {profile_dict.get('avg_roi',0)}
first_seen: {profile_dict.get('first_seen','')}
last_seen_ts: {profile_dict.get('last_seen_ts',0)}
---

# Whale Profile — Lifetime Stats

**Wallet:** `{wallet}`
**Display Name:** {profile_dict.get('name','')}
**Total Positions:** {profile_dict.get('total_positions',0)}
**Wins:** {profile_dict.get('total_wins',0)} | **Losses:** {profile_dict.get('losses',0)}
**Lifetime Win Rate:** {profile_dict.get('win_rate',0):.1f}%
**30-Day Win Rate:** {profile_dict.get('win_rate_30d',0):.1f}%
**90-Day Win Rate:** {profile_dict.get('win_rate_90d',0):.1f}%
**6-Month Win Rate:** {profile_dict.get('win_rate_6m',0):.1f}%
**Current Streak:** {profile_dict.get('current_streak',0)} | **Longest Streak:** {profile_dict.get('longest_streak',0)}
**Total PnL:** ${profile_dict.get('total_pnl',0):,.2f}
**Avg ROI:** {profile_dict.get('avg_roi',0):.1f}%
**First Seen:** {profile_dict.get('first_seen','')}
**Last Updated:** {profile_dict.get('updated_at','')}
"""
    path.write_text(text)
    return path

def ingest_whale(wallet: str, profile: dict):
    """Write/overwrite a whale profile to brain/polyshark/whales/."""
    safe = wallet.lower().replace('0x', '')[:16]
    path = VAULT / 'whales' / f"{safe}.md"
    text = f"""---
type: whale_profile
wallet: {wallet}
updated: {now()}
rank: {profile.get('rank','')}
vol: {profile.get('vol', 0)}
pnl: {profile.get('pnl', 0)}
name: {profile.get('name','')}
win_rate_30d: {profile.get('win_rate', 0)}
win_streak: {profile.get('win_streak', 0)}
is_high_freq: {wallet.lower() == '0x63a51cbb37341837b873bc29d05f482bc2988e33'.lower()}
---

# Whale Profile — {profile.get('name', wallet[:12])}

**Wallet:** `{wallet}`
**Display Name:** {profile.get('name','')}
**Rank:** #{profile.get('rank','')}
**Volume:** ${profile.get('vol', 0):,.0f}
**PnL:** ${profile.get('pnl', 0):,.0f}
**30-Day Win Rate:** {profile.get('win_rate', 0):.0f}%
**Current Win Streak:** {profile.get('win_streak', 0)}
**High Freq Tag:** {'YES 🏅' if wallet.lower() == '0x63a51cbb37341837b873bc29d05f482bc2988e33'.lower() else 'No'}
"""
    path.write_text(text)
    return path

# ─── Streaks ───────────────────────────────────────────────────────────────────

def ingest_streak(wallet: str, streak: int, profile: dict):
    """Write a streak event to brain/polyshark/streaks/."""
    safe = wallet.lower().replace('0x', '')[:16]
    ts = now().replace(' ', '_').replace(':', '')
    tier = 'ON FIRE' if streak >= 8 else 'HOT'
    path = VAULT / 'streaks' / f"{ts}_{safe}_{streak}wins.md"
    text = f"""---
type: streak_event
wallet: {wallet}
streak: {streak}
tier: {tier}
timestamp: {now()}
profit_last: {profile.get('profit_usdc',0)}
roi_last: {profile.get('roi_pct',0)}
market: {profile.get('question','')[:80]}
---

# {tier} — {streak}-Win Streak

**Wallet:** `{wallet}`
**Streak:** {streak} consecutive wins
**Tier:** {tier}
**Last Win:** ${profile.get('profit_usdc', 0):,.0f} | {profile.get('roi_pct',0):.0f}% ROI
**Market:** {profile.get('question','')[:80]}
"""
    path.write_text(text)
    return path

# ─── Rank Changes ─────────────────────────────────────────────────────────────

def ingest_rank_change(wallet: str, prev_rank, new_rank, profile: dict):
    """Write a rank change to brain/polyshark/rank-changes/."""
    safe = wallet.lower().replace('0x', '')[:16]
    ts = now().replace(' ', '_').replace(':', '')
    direction = 'UP' if int(new_rank) < int(prev_rank) else 'DOWN'
    path = VAULT / 'rank-changes' / f"{ts}_{safe}_{direction}.md"
    text = f"""---
type: rank_change
wallet: {wallet}
prev_rank: {prev_rank}
new_rank: {new_rank}
direction: {direction}
timestamp: {now()}
vol: {profile.get('vol',0)}
pnl: {profile.get('pnl',0)}
---

# Rank {direction} — #{prev_rank} → #{new_rank}

**Wallet:** `{wallet}`
**Display Name:** {profile.get('name','')}
**Change:** #{prev_rank} → #{new_rank}
**Direction:** {direction}
**Volume:** ${profile.get('vol', 0):,.0f}
**PnL:** ${profile.get('pnl', 0):,.0f}
"""
    path.write_text(text)
    return path

# ─── Markets ──────────────────────────────────────────────────────────────────

def ingest_market(market_id: str, question: str, outcome: str, profit: float, roi: float, volume: float):
    """Write a resolved market to brain/polyshark/markets/."""
    safe = market_id[:16]
    path = VAULT / 'markets' / f"{safe}.md"
    text = f"""---
type: market_resolved
market_id: {market_id}
question: {question[:80]}
outcome: {outcome}
profit: {profit}
roi: {roi}
volume: {volume}
timestamp: {now()}
---

# Market Resolved — {question[:60]}

**Market:** {question[:80]}
**Winning Outcome:** {outcome}
**Whale Profit:** ${profit:,.0f} ({roi:.0f}% ROI)
**Market Volume:** ${volume:,.0f}

**Link:** https://polymarket.com/event/{market_id}
"""
    path.write_text(text)
    return path

if __name__ == '__main__':
    # Quick test
    ingest_fault('rate_limit', 'Too Many Requests', {'chat_id': '-1003739747776', 'retry_after': 22})
    print('OMPA Polyshark memory: test write OK')
