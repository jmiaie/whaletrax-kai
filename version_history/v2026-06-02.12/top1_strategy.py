#!/usr/bin/env python3
"""
TOP-1 DAILY STRATEGY — v1.0
Identifies the single highest-multiple trade per day from 100% WR whale wallets.
Run daily via cron or manually.
"""
import sys, os, json, logging
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
ROOT = '/home/ubuntu/.openclaw/workspace'
REPO = f'{ROOT}/repos/whaletrax'
SYS  = f'{ROOT}/repos/system'
if ROOT not in sys.path: sys.path.insert(0, ROOT)
if REPO not in sys.path: sys.path.insert(0, REPO)
os.chdir(REPO)

logging.basicConfig(
    filename='logs/top1_strategy.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger('top1')

# ── Parameters ─────────────────────────────────────────────────────────────────
FRAC          = 0.15        # 15% of balance per trade
MIN_MULT      = 0.25        # Skip if mult below this
MAX_POS_SIZE  = 500.00      # Cap per trade
MIN_POS_SIZE  = 2.00        # Floor per trade
WR_THRESHOLD  = 100.0       # 100% WR requirement
MIN_POS_COUNT = 10          # Minimum lifetime positions
TOP_N         = 1           # Top-1 only
PRO_CHANNELS  = {
    'hub': -1003786930778,   # PolysharkPro
    'mgmt': -1003903150516,  # Polyshark Mgmt
}

# ── Wallet profiles ────────────────────────────────────────────────────────────
def load_wallet_profiles():
    path = Path('/tmp/wallet_profiles.json')
    if not path.exists():
        log.warning('wallet_profiles.json not found at /tmp — run wallet scanner first')
        return {}
    with open(path) as f:
        return json.load(f)

def filter_100wr(wallets):
    """Return wallets with 100% win rate and 10+ lifetime positions."""
    return {
        addr: w for addr, w in wallets.items()
        if w.get('win_rate') == WR_THRESHOLD
        and w.get('total_positions', 0) >= MIN_POS_COUNT
    }

def get_active_positions(wallets):
    """
    Get all active positions across qualifying wallets.
    Active = any position in _pos_history with ts within last 7 days.
    Returns list of dicts with mult, pnl, sz, wallet, ts, market_question, etc.
    """
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - 7 * 86400  # 7 days
    positions = []

    for addr, w in wallets.items():
        for p in w.get('_pos_history', []):
            ts = p.get('ts', 0)
            if ts < cutoff:
                continue
            pnl = p.get('pnl', 0) or 0
            sz  = max(p.get('sz', 0), 0.01)
            mult = pnl / sz
            if mult < MIN_MULT:
                continue  # skip low-quality signals
            positions.append({
                'wallet': addr,
                'name': w.get('name', addr[:10]),
                'ts': ts,
                'pnl': pnl,
                'sz': sz,
                'mult': mult,
                'wr': w.get('win_rate', 0),
                'total_positions': w.get('total_positions', 0),
                'total_pnl': w.get('total_pnl', 0),
                'wr_30d': w.get('win_rate_30d', 0),
                'pnl_30d': w.get('pnl_30d', 0),
                'last_seen': w.get('last_seen_ts', 0),
                'age_hours': (now - ts) / 3600 if ts > 0 else 999,
            })
    return positions

# ── Ranking & Selection ────────────────────────────────────────────────────────
def select_top1(positions):
    """Sort by mult descending, return top-1."""
    if not positions:
        return None
    positions.sort(key=lambda x: x['mult'], reverse=True)
    return positions[0]

# ── Formatting ─────────────────────────────────────────────────────────────────
def fmt_currency(v):
    return f'+${v:,.2f}' if v >= 0 else f'-${abs(v):,.2f}'

def format_signal(trade, balance, fraction):
    """Build the Telegram text card for a TOP-1 signal."""
    pos_size = max(min(balance * fraction, MAX_POS_SIZE), MIN_POS_SIZE)
    mult = trade['mult']
    age_days = trade['age_hours'] / 24

    # Tier label
    if mult > 0.80:
        tier = 'A+'
        tier_badge = '🎯 A+ SIGNAL'
    elif mult > 0.50:
        tier = 'A'
        tier_badge = '🎯 A SIGNAL'
    elif mult > 0.30:
        tier = 'B'
        tier_badge = '🎯 B SIGNAL'
    else:
        tier = 'C'
        tier_badge = '🎯 C SIGNAL'

    # Market question
    q = f"TOP-1 DAILY SIGNAL | Tier {tier} | Mult {mult:.3f}×"
    age_label = f"{age_days:.1f} days ago" if age_days >= 1 else f"{trade['age_hours']:.0f} hrs ago"

    wallet_short = f"{trade['wallet'][:8]}...{trade['wallet'][-6:]}"
    wallet_link = f"[{wallet_short}](https://polymarket.com/profile/{trade['wallet']})"

    lines = [
        f"{tier_badge}",
        f"━━━━━━━━━━━━━━━━━━",
        f"📊 Compounding @ {int(fraction*100)}% | Bal: ${balance:,.2f}",
        f"🎯 Position Size: ${pos_size:,.2f}",
        f"━━━━━━━━━━━━━━━━━━",
        f"🐋 {wallet_link}",
        f"📈 Win Rate: {trade['wr']:.0f}% ({trade['total_positions']} trades)",
        f"💰 Total P/L: {fmt_currency(trade['total_pnl'])}",
        f"⏱ Opened: {age_label}",
        f"━━━━━━━━━━━━━━━━━━",
        f"🏆 MULTIPLIER: {mult:.4f}× per dollar",
        f"📦 Size: ${trade['sz']:,.2f} → P/L: {fmt_currency(trade['pnl'])}",
        f"🔍 Strategy: Top-1 Daily | 100% WR Filter",
    ]
    return '\n'.join(lines)

# ── Alert sending ──────────────────────────────────────────────────────────────
def send_alert(text, channel='hub'):
    """Send text alert to Telegram channel."""
    token = os.environ.get('POLYSHARK_BOT_TOKEN', '')
    if not token:
        log.warning('POLYSHARK_BOT_TOKEN not set — cannot send alert')
        return False
    import requests
    cid = PRO_CHANNELS.get(channel)
    if not cid:
        log.error(f'Unknown channel: {channel}')
        return False
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    data = {'chat_id': cid, 'text': text, 'parse_mode': 'Markdown'}
    try:
        r = requests.post(url, data=data, timeout=15)
        if r.ok:
            log.info(f'Alert sent to {channel}')
            return True
        else:
            log.error(f'Alert failed: {r.text}')
            return False
    except Exception as e:
        log.error(f'Send error: {e}')
        return False

# ── Balance tracking ───────────────────────────────────────────────────────────
STATE_FILE = Path('/tmp/top1_strategy_state.json')

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {'balance': 500.0, 'start_balance': 500.0, 'trades': [], 'escalations': 0}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

def update_balance(trade, fraction):
    """Update balance based on trade result (call after market resolves)."""
    state = load_state()
    pos_size = max(min(state['balance'] * fraction, MAX_POS_SIZE), MIN_POS_SIZE)
    ret = pos_size * trade['mult']
    new_balance = max(state['balance'] + ret, 0.01)
    state['balance'] = new_balance

    # Check for escalation
    if new_balance >= state['start_balance'] * 3 and state['escalations'] == 0:
        state['escalations'] = 1
        log.info(f'ESCALATION: Balance tripled to ${new_balance:,.2f}')

    state['trades'].append({
        'ts': datetime.now(timezone.utc).isoformat(),
        'wallet': trade['wallet'],
        'mult': trade['mult'],
        'pnl': trade['pnl'],
        'sz': trade['sz'],
        'pos_size': pos_size,
        'ret': ret,
        'balance_after': new_balance,
    })
    save_state(state)
    return new_balance

# ── Main entry point ───────────────────────────────────────────────────────────
def run(balance=None):
    """
    Run the TOP-1 strategy.
    Pass balance=None to use tracked state balance.
    Pass balance=<float> to override (e.g. 500.0 for fresh run).
    """
    log.info('=== TOP-1 Strategy Run ===')

    # Load wallets
    wallets = load_wallet_profiles()
    if not wallets:
        log.error('No wallets loaded — aborting')
        return None

    # Filter 100% WR
    wr100 = filter_100wr(wallets)
    log.info(f'Wallets: {len(wallets)} total | 100% WR (10+ trades): {len(wr100)}')

    if not wr100:
        log.error('No qualifying 100% WR wallets found')
        return None

    # Get active positions
    positions = get_active_positions(wr100)
    log.info(f'Active positions: {len(positions)}')

    if not positions:
        log.warning('No active positions found above mult threshold')
        return None

    # Select top-1
    top1 = select_top1(positions)
    log.info(f'Top-1 selected: mult={top1["mult"]:.4f} | wallet={top1["wallet"][:12]}... '
             f'| pnl={top1["pnl"]:.2f} | sz={top1["sz"]:.2f}')

    # Load state
    state = load_state()
    if balance is None:
        balance = state['balance']

    pos_size = max(min(balance * FRAC, MAX_POS_SIZE), MIN_POS_SIZE)

    # Format and send alert
    card = format_signal(top1, balance, FRAC)
    ok = send_alert(card, 'hub')
    if ok:
        log.info(f'Signal alert sent — position size: ${pos_size:.2f}')
    else:
        log.warning('Failed to send signal alert')

    # Return signal details for logging
    return {
        'wallet': top1['wallet'],
        'mult': top1['mult'],
        'pnl': top1['pnl'],
        'sz': top1['sz'],
        'pos_size': pos_size,
        'balance': balance,
        'fraction': FRAC,
        'age_hours': top1['age_hours'],
        'wr': top1['wr'],
        'total_positions': top1['total_positions'],
        'sent': ok,
    }

if __name__ == '__main__':
    result = run()
    if result:
        print(f"✅ TOP-1 SIGNAL FOUND")
        print(f"   Wallet: {result['wallet'][:12]}...")
        print(f"   Multiplier: {result['mult']:.4f}×")
        print(f"   Position: ${result['sz']:,.2f}")
        print(f"   P/L: {fmt_currency(result['pnl'])}")
        print(f"   Suggested size: ${result['pos_size']:.2f}")
    else:
        print("❌ No qualifying signal found today")