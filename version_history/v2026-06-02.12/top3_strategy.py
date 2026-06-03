#!/usr/bin/env python3
"""
TOP-3 DAILY STRATEGY — v1.0
Production strategy: Top-3 plays/day, 25% total fraction, tiered caps.
Real whale on-chain data from 100% WR wallets.
Run via cron or daemon mode.
"""
import sys, os, json, logging, time
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
ROOT = '/home/ubuntu/.openclaw/workspace'
REPO = f'{ROOT}/repos/whaletrax'
if ROOT not in sys.path: sys.path.insert(0, ROOT)
if REPO not in sys.path: sys.path.insert(0, REPO)
os.chdir(REPO)

logging.basicConfig(
    filename='logs/top3_strategy.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger('top3')

# ── Strategy Parameters ──────────────────────────────────────────────────────────
FRAC_TOTAL  = 0.25        # 25% of balance total daily exposure
TOP_N       = 3            # 3 plays per day
SCAN_INTERVAL = 30          # seconds between scans (fast mode)
MIN_MULT    = 0.25
WR_THRESHOLD = 100.0
MIN_POS_COUNT = 10
COOLDOWN_SEC = 300          # 5 min dedup per wallet+mult

PRO_CHANNELS = {
    'hub': -1003786930778,
    'mgmt': -1003903150516,
}

# ── Import position sizer ────────────────────────────────────────────────────────
sys.path.insert(0, REPO)
try:
    from position_sizer import get_cap, calc_position_size
    log.info('position_sizer loaded OK')
except Exception as e:
    log.warning(f'position_sizer import failed: {e}')
    # Fallback inline
    def get_cap(balance):
        caps = [(5000,500),(20000,1000),(50000,2500),(200000,5000),(float('inf'),10000)]
        for threshold, cap in caps:
            if balance <= threshold:
                return cap
        return 10000
    def calc_position_size(balance, frac, n):
        per = frac / n
        cap = get_cap(balance)
        return [max(min(balance * per, cap), 2.00) for _ in range(n)]

STATE_FILE = Path('/tmp/top3_strategy_state.json')
SENT_FILE = Path('/tmp/top3_strategy_sent.json')

# ── Wallet loading ──────────────────────────────────────────────────────────────
def load_wallets():
    path = Path('/tmp/wallet_profiles.json')
    if not path.exists():
        log.warning('wallet_profiles.json not found')
        return {}
    with open(path) as f:
        return json.load(f)

def filter_100wr(wallets):
    return {
        addr: w for addr, w in wallets.items()
        if w.get('win_rate') == WR_THRESHOLD
        and w.get('total_positions', 0) >= MIN_POS_COUNT
    }

def get_positions(wallets, max_age_hours=168):
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - max_age_hours * 3600
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
                'ts': ts,
                'pnl': pnl,
                'sz': sz,
                'mult': mult,
                'wr': w.get('win_rate', 0),
                'total_positions': w.get('total_positions', 0),
                'total_pnl': w.get('total_pnl', 0),
                'age_hours': (now - ts) / 3600,
                'name': w.get('name', addr[:10]),
            })
    return positions

# ── Selection ──────────────────────────────────────────────────────────────────
def select_top_n(positions, n=3):
    if not positions:
        return []
    positions.sort(key=lambda x: x['mult'], reverse=True)
    selected = []
    used_wallets = set()
    for p in positions:
        if len(selected) >= n:
            break
        if p['wallet'] not in used_wallets or len(positions) < n:
            selected.append(p)
            used_wallets.add(p['wallet'])
    return selected

# ── Dedup ─────────────────────────────────────────────────────────────────────
def load_sent():
    if SENT_FILE.exists():
        return json.loads(SENT_FILE.read_text())
    return {}

def save_sent(sent):
    SENT_FILE.write_text(json.dumps(sent))

def is_cooldown(wallet, mult):
    sent = load_sent()
    key = f"{wallet}:{round(mult, 4)}"
    if key in sent:
        return True
    # Keep last 500 entries
    sent[key] = True
    if len(sent) > 500:
        sent = dict(list(sent.items())[-500:])
    save_sent(sent)
    return False

# ── Formatting ──────────────────────────────────────────────────────────────────
def fmt_currency(v):
    return f'+${v:,.2f}' if v >= 0 else f'-${abs(v):,.2f}'

def tier(mult):
    if mult > 0.80: return 'A+'
    elif mult > 0.50: return 'A'
    elif mult > 0.30: return 'B'
    else: return 'C'

def format_card(trades, balance, frac_total=0.25, top_n=3):
    per_trade_frac = frac_total / top_n
    cap = get_cap(balance)
    cap_tier_info = f"${cap:,}/pos"

    lines = [
        f"🎯 TOP-{top_n} DAILY | {int(frac_total*100)}% total | {int(per_trade_frac*100)}%/trade",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 Balance: ${balance:,.2f} | Cap: {cap_tier_info} | Total deploy: ${balance*frac_total:,.2f}",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    total_mult = 0
    for i, trade in enumerate(trades, 1):
        mult = trade['mult']
        total_mult += mult
        age = trade['age_hours']
        age_label = f"{age/24:.1f}d ago" if age >= 24 else f"{age:.0f}h ago"
        wshort = f"{trade['wallet'][:8]}...{trade['wallet'][-6:]}"
        pos_size = min(balance * per_trade_frac, cap)
        t = tier(mult)
        lines += [
            f"",
            f"#{i} [{t}] mult {mult:.4f}×",
            f"   🐋 [{wshort}](https://polymarket.com/profile/{trade['wallet']})",
            f"   WR: {trade['wr']:.0f}% | {trade['total_positions']} trades | {age_label}",
            f"   💰 {fmt_currency(trade['pnl'])} on ${trade['sz']:,.0f}",
            f"   🎯 Size: ${pos_size:,.2f} | Eff: {pos_size/balance*100:.1f}% of bal",
        ]

    avg_mult = total_mult / len(trades) if trades else 0
    lines += [
        f"",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📈 Avg mult: {avg_mult:.4f}× | Combined: {total_mult:.4f}×",
        f"🔍 Top-{top_n} Strategy | 100% WR | Tiered Sizing | v2026-06-02",
    ]
    return '\n'.join(lines)

# ── Telegram ───────────────────────────────────────────────────────────────────
def send(text, channel='hub'):
    token = os.environ.get('POLYSHARK_BOT_TOKEN', '')
    if not token:
        log.warning('BOT_TOKEN not set')
        return False
    import requests
    cid = PRO_CHANNELS.get(channel)
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    data = {'chat_id': cid, 'text': text, 'parse_mode': 'Markdown'}
    try:
        r = requests.post(url, data=data, timeout=15)
        return r.ok
    except Exception as e:
        log.error(f'Send error: {e}')
        return False

# ── State ───────────────────────────────────────────────────────────────────────
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {'balance': 2000.0, 'start_balance': 2000.0, 'trades': [], 'escalations': 0}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

# ── Main scan ────────────────────────────────────────────────────────────────
def do_scan(balance_override=None):
    wallets = load_wallets()
    if not wallets:
        log.warning('No wallets')
        return None

    wr100 = filter_100wr(wallets)
    positions = get_positions(wr100)
    if not positions:
        log.info('No qualifying positions')
        return None

    top_trades = select_top_n(positions, TOP_N)
    if not top_trades:
        return None

    state = load_state()
    balance = balance_override if balance_override is not None else state['balance']

    # Check dedup — skip if any trade is on cooldown
    new_trades = []
    for trade in top_trades:
        if not is_cooldown(trade['wallet'], trade['mult']):
            new_trades.append(trade)

    if not new_trades:
        log.info('All top trades on cooldown')
        return None

    card = format_card(new_trades, balance, FRAC_TOTAL, TOP_N)
    ok = send(card, 'hub')
    log.info(f'Top-{TOP_N} signal sent: {[t["mult"] for t in new_trades]} | bal: ${balance:,.2f}')

    # Update state
    state['trades'].append({
        'ts': datetime.now(timezone.utc).isoformat(),
        'n_positions': len(new_trades),
        'mults': [t['mult'] for t in new_trades],
        'balance': balance,
    })
    save_state(state)

    return {
        'trades': new_trades,
        'balance': balance,
        'sent': ok,
    }

# ── Daemon ─────────────────────────────────────────────────────────────────
def run_daemon(interval=SCAN_INTERVAL):
    log.info(f'Top-{TOP_N} strategy daemon started — polling every {interval}s')
    while True:
        try:
            do_scan()
        except Exception as e:
            log.error(f'Scan error: {e}')
        time.sleep(interval)

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--daemon', action='store_true')
    parser.add_argument('--interval', type=int, default=SCAN_INTERVAL)
    parser.add_argument('--balance', type=float, default=None, help='Override balance')
    args = parser.parse_args()

    if args.once or (not args.daemon):
        result = do_scan(args.balance)
        if result:
            print(f"✅ Top-{TOP_N} signal sent — {len(result['trades'])} plays | bal: ${result['balance']:,.2f}")
            for i, t in enumerate(result['trades'], 1):
                print(f"  #{i} mult={t['mult']:.4f}× | {t['wallet'][:12]}...")
        else:
            print(f"⏳ No new signals (all on cooldown or no positions)")
    elif args.daemon:
        run_daemon(args.interval)