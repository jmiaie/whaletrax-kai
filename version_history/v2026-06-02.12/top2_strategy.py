#!/usr/bin/env python3
"""
TOP-2 DAILY STRATEGY — v1.0
Identifies the 2 highest-multiple trades per day from 100% WR whale wallets.
Diversification: 2 plays, each at 7.5% of balance (total 15% daily exposure).
Run daily via cron or manually.
"""
import sys, os, json, logging
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
ROOT = '/home/ubuntu/.openclaw/workspace'
REPO = f'{ROOT}/repos/whaletrax'
if ROOT not in sys.path: sys.path.insert(0, ROOT)
if REPO not in sys.path: sys.path.insert(0, REPO)
os.chdir(REPO)

logging.basicConfig(
    filename='logs/top2_strategy.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger('top2')

# ── Parameters ─────────────────────────────────────────────────────────────────
FRAC          = 0.15        # TOTAL daily exposure
TOP_N         = 2           # 2 plays per day
PER_TRADE_FRAC = FRAC / TOP_N  # 7.5% per trade
MIN_MULT      = 0.25        # Skip if mult below this
MAX_POS_SIZE  = 500.00      # Cap per single trade
MIN_POS_SIZE  = 2.00        # Floor per single trade
WR_THRESHOLD  = 100.0
MIN_POS_COUNT = 10
PRO_CHANNELS  = {
    'hub': -1003786930778,
    'mgmt': -1003903150516,
}

# ── Wallet profiles ────────────────────────────────────────────────────────────
def load_wallet_profiles():
    path = Path('/tmp/wallet_profiles.json')
    if not path.exists():
        log.warning('wallet_profiles.json not found at /tmp')
        return {}
    with open(path) as f:
        return json.load(f)

def filter_100wr(wallets):
    return {
        addr: w for addr, w in wallets.items()
        if w.get('win_rate') == WR_THRESHOLD
        and w.get('total_positions', 0) >= MIN_POS_COUNT
    }

def get_active_positions(wallets):
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - 7 * 86400
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
                continue
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
                'age_hours': (now - ts) / 3600 if ts > 0 else 999,
            })
    return positions

# ── Ranking & Selection ────────────────────────────────────────────────────────
def select_top_n(positions, n=2):
    if not positions:
        return []
    positions.sort(key=lambda x: x['mult'], reverse=True)
    # Ensure they come from different wallets (diversification requirement)
    selected = []
    wallets_used = set()
    for p in positions:
        if len(selected) >= n:
            break
        # Allow same wallet only if we have to (not enough unique wallets)
        if p['wallet'] not in wallets_used or len(positions) < n:
            selected.append(p)
            wallets_used.add(p['wallet'])
    return selected

# ── Formatting ─────────────────────────────────────────────────────────────────
def fmt_currency(v):
    return f'+${v:,.2f}' if v >= 0 else f'-${abs(v):,.2f}'

def tier_badge(mult):
    if mult > 0.80: return 'A+'
    elif mult > 0.50: return 'A'
    elif mult > 0.30: return 'B'
    else: return 'C'

def format_signal(trades, balance, total_frac=0.15, top_n=2):
    """Build the Telegram text card for a TOP-N signal."""
    per_trade_frac = total_frac / top_n

    # Header
    lines = [
        f"🎯 TOP-{top_n} DAILY SIGNAL | 2-PLAY DIVERSIFICATION",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 Compounding @ {int(total_frac*100)}% total | {int(per_trade_frac*100)}% per trade | Bal: ${balance:,.2f}",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    for i, trade in enumerate(trades, 1):
        mult = trade['mult']
        pos_size = max(min(balance * per_trade_frac, MAX_POS_SIZE), MIN_POS_SIZE)
        tier = tier_badge(mult)
        age_days = trade['age_hours'] / 24
        age_label = f"{age_days:.1f}d ago" if age_days >= 1 else f"{trade['age_hours']:.0f}h ago"
        wallet_short = f"{trade['wallet'][:8]}...{trade['wallet'][-6:]}"

        lines += [
            f"",
            f"#{i} [{tier}] MULT: {mult:.4f}×",
            f"🐋 [0xd1a63a...ab1507](https://polymarket.com/profile/{trade['wallet']})",
            f"   WR: {trade['wr']:.0f}% ({trade['total_positions']} trades) | {age_label}",
            f"   💰 P/L: {fmt_currency(trade['pnl'])} on ${trade['sz']:,.2f}",
            f"   🎯 Size: ${pos_size:.2f} per trade",
        ]

    total_mult = sum(t['mult'] for t in trades)
    combined_mult = total_mult  # total daily mult across both plays

    lines += [
        f"",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📈 COMBINED MULTIPLIER: {combined_mult:.4f}×",
        f"💡 Strategy: Top-{top_n} Daily | 100% WR | Diversified",
    ]
    return '\n'.join(lines)

def format_single_signal(trade, balance, fraction, label='#1'):
    """Format a single trade signal (used for Top-1 or each leg of Top-2)."""
    mult = trade['mult']
    pos_size = max(min(balance * fraction, MAX_POS_SIZE), MIN_POS_SIZE)
    tier = tier_badge(mult)
    age_days = trade['age_hours'] / 24
    age_label = f"{age_days:.1f}d ago" if age_days >= 1 else f"{trade['age_hours']:.0f}h ago"
    wallet_short = f"{trade['wallet'][:8]}...{trade['wallet'][-6:]}"
    return {
        'label': label,
        'tier': tier,
        'mult': mult,
        'wallet': trade['wallet'],
        'wallet_short': wallet_short,
        'wr': trade['wr'],
        'total_positions': trade['total_positions'],
        'total_pnl': trade['total_pnl'],
        'pnl': trade['pnl'],
        'sz': trade['sz'],
        'age_label': age_label,
        'pos_size': pos_size,
        'fraction': fraction,
    }

# ── Alert sending ──────────────────────────────────────────────────────────────
def send_alert(text, channel='hub'):
    token = os.environ.get('POLYSHARK_BOT_TOKEN', '')
    if not token:
        log.warning('POLYSHARK_BOT_TOKEN not set')
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
STATE_FILE = Path('/tmp/top2_strategy_state.json')

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {'balance': 500.0, 'start_balance': 500.0, 'trades': [], 'escalations': 0}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

# ── Main entry point ───────────────────────────────────────────────────────────
def run(balance=None):
    log.info('=== TOP-2 Strategy Run ===')

    wallets = load_wallet_profiles()
    if not wallets:
        log.error('No wallets loaded')
        return None

    wr100 = filter_100wr(wallets)
    log.info(f'Wallets: {len(wallets)} total | 100% WR: {len(wr100)}')

    positions = get_active_positions(wr100)
    log.info(f'Active positions: {len(positions)}')

    if not positions:
        log.warning('No active positions found')
        return None

    top_n_trades = select_top_n(positions, TOP_N)
    if not top_n_trades or len(top_n_trades) < TOP_N:
        log.warning(f'Only {len(top_n_trades)} qualifying trades found (need {TOP_N})')
        return None

    state = load_state()
    if balance is None:
        balance = state['balance']

    # Build signals for each trade
    signals = []
    for i, trade in enumerate(top_n_trades, 1):
        sig = format_single_signal(trade, balance, PER_TRADE_FRAC, label=f'#{i}')
        signals.append(sig)

    # Format combined card
    card = format_signal(top_n_trades, balance, total_frac=FRAC, top_n=TOP_N)
    ok = send_alert(card, 'hub')

    log.info(f'Top-2 signals: {[s["mult"] for s in signals]}')
    if ok:
        log.info(f'Signal alert sent — {len(signals)} plays at {PER_TRADE_FRAC*100:.1f}% each')

    return {
        'signals': signals,
        'balance': balance,
        'per_trade_frac': PER_TRADE_FRAC,
        'total_frac': FRAC,
        'sent': ok,
        'top_n': TOP_N,
        'trades': top_n_trades,
    }

if __name__ == '__main__':
    result = run()
    if result:
        print(f"✅ TOP-2 SIGNALS FOUND — {len(result['signals'])} plays")
        for s in result['signals']:
            print(f"   [{s['label']}] {s['tier']} | mult={s['mult']:.4f} | "
                  f"size=${s['pos_size']:.2f} | {s['wallet_short']} | WR {s['wr']:.0f}%")
    else:
        print("❌ No qualifying signals found today")