#!/usr/bin/env python3
"""
FAST-SCAN DAEMON — v1.0
Runs continuously, checks for new whale positions every 30 seconds.
Generates TOP-1 and TOP-2 signals as soon as they appear.
Slippage-conscious: minimum latency from whale entry to alert.
"""
import sys, os, json, logging, time, threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = '/home/ubuntu/.openclaw/workspace'
REPO = f'{ROOT}/repos/whaletrax'
if ROOT not in sys.path: sys.path.insert(0, ROOT)
if REPO not in sys.path: sys.path.insert(0, REPO)
os.chdir(REPO)

logging.basicConfig(
    filename='logs/fast_scan.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger('fastscan')

# ── Parameters ─────────────────────────────────────────────────────────────────
SCAN_INTERVAL  = 30          # seconds between scans ← FAST (was 120s router, 300s wallet)
FRAC_TOP1      = 0.25        # 25% per trade
FRAC_TOP2_TOTAL= 0.25        # 25% total, 12.5% per trade
MIN_MULT       = 0.25
MAX_POS_SIZE   = 500.00
MIN_POS_SIZE   = 2.00
WR_THRESHOLD   = 100.0
MIN_POS_COUNT  = 10
TOP_N          = 2           # scan top-2 for diversification option
SIGNAL_COOLDOWN= 300         # seconds before same wallet+market can trigger again

STATE_FILE     = Path('/tmp/fast_scan_state.json')
SENT_FILE      = Path('/tmp/fast_scan_sent.json')  # dedup log
PRO_CHANNELS   = {'hub': -1003786930778, 'mgmt': -1003903150516}

# ── Load wallet profiles ─────────────────────────────────────────────────────────
def load_wallets():
    path = Path('/tmp/wallet_profiles.json')
    if not path.exists():
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
    """Get all active positions within max_age_hours across 100% WR wallets."""
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
            })
    return positions

# ── Dedup ─────────────────────────────────────────────────────────────────────
def load_sent():
    if SENT_FILE.exists():
        return set(json.loads(SENT_FILE.read_text()).keys())
    return set()

def save_sent(sent):
    SENT_FILE.write_text(json.dumps({k: True for k in sent}, indent=2))

def is_cooldown(wallet, mult, cooldown=SIGNAL_COOLDOWN):
    """Skip if same wallet+mult was sent in last cooldown seconds."""
    sent = load_sent()
    key = f"{wallet}:{round(mult, 4)}"
    if key in sent:
        return True
    # Add to sent
    sent.add(key)
    # Prune old entries (keep last 500)
    if len(sent) > 500:
        save_sent(set(list(sent)[-500:]))
    else:
        save_sent(sent)
    return False

# ── Selection ─────────────────────────────────────────────────────────────────
def select_top_n(positions, n=2):
    if not positions:
        return []
    positions.sort(key=lambda x: x['mult'], reverse=True)
    selected = []
    seen_wallets = set()
    for p in positions:
        if len(selected) >= n:
            break
        if p['wallet'] not in seen_wallets or len(positions) < n:
            selected.append(p)
            seen_wallets.add(p['wallet'])
    return selected

# ── Formatting ─────────────────────────────────────────────────────────────────
def fmt_currency(v):
    return f'+${v:,.2f}' if v >= 0 else f'-${abs(v):,.2f}'

def tier(mult):
    if mult > 0.80: return 'A+'
    elif mult > 0.50: return 'A'
    elif mult > 0.30: return 'B'
    else: return 'C'

def format_top1(trade, balance, frac=0.25):
    pos_size = max(min(balance * frac, MAX_POS_SIZE), MIN_POS_SIZE)
    mult = trade['mult']
    age_days = trade['age_hours'] / 24
    age_label = f"{age_days:.1f}d ago" if age_days >= 1 else f"{trade['age_hours']:.0f}h ago"
    t = tier(mult)
    wshort = f"{trade['wallet'][:8]}...{trade['wallet'][-6:]}"
    lines = [
        f"🎯 TOP-1 SIGNAL [{t}] @ {int(frac*100)}%",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 Balance: ${balance:,.2f} → Size: ${pos_size:.2f}",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🐋 [{wshort}](https://polymarket.com/profile/{trade['wallet']})",
        f"   WR: {trade['wr']:.0f}% | {trade['total_positions']} trades",
        f"   💰 {fmt_currency(trade['total_pnl'])} lifetime",
        f"   ⏱ {age_label}",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🏆 MULT: {mult:.4f}× | ${trade['sz']:,.0f} pos → {fmt_currency(trade['pnl'])}",
        f"🔍 Top-1 Fast Scan | 30s Polling | v2026-06-02",
    ]
    return '\n'.join(lines)

def format_top2(trades, balance, frac=0.25, top_n=2):
    per_trade = frac / top_n
    lines = [
        f"🎯 TOP-{top_n} DAILY SIGNAL [{int(frac*100)}% total | {int(per_trade*100)}%/trade]",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 Balance: ${balance:,.2f} | Total: ${balance*frac:.2f}",
    ]
    for i, trade in enumerate(trades, 1):
        pos_size = max(min(balance * per_trade, MAX_POS_SIZE), MIN_POS_SIZE)
        mult = trade['mult']
        age_label = f"{trade['age_hours']/24:.1f}d ago" if trade['age_hours'] >= 24 else f"{trade['age_hours']:.0f}h ago"
        t = tier(mult)
        wshort = f"{trade['wallet'][:8]}...{trade['wallet'][-6:]}"
        lines += [
            f"",
            f"#{i} [{t}] mult={mult:.4f}×",
            f"  🐋 [{wshort}](https://polymarket.com/profile/{trade['wallet']})",
            f"  💰 {fmt_currency(trade['pnl'])} on ${trade['sz']:,.0f}",
            f"  ⏱ {age_label} | WR {trade['wr']:.0f}%",
            f"  🎯 Size: ${pos_size:.2f}",
        ]
    lines += [f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", f"🔍 Top-{top_n} Fast Scan | 30s Polling | v2026-06-02"]
    return '\n'.join(lines)

# ── Telegram ───────────────────────────────────────────────────────────────────
def send(text, channel='hub'):
    token = os.environ.get('POLYSHARK_BOT_TOKEN', '')
    if not token:
        log.warning('BOT_TOKEN not set')
        return False
    import requests
    cid = PRO_CHANNELS.get(channel)
    if not cid:
        return False
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    data = {'chat_id': cid, 'text': text, 'parse_mode': 'Markdown'}
    try:
        r = requests.post(url, data=data, timeout=15)
        return r.ok
    except Exception as e:
        log.error(f'Send error: {e}')
        return False

# ── Balance ────────────────────────────────────────────────────────────────────
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {'balance': 500.0, 'start_balance': 500.0, 'trades': [], 'escalations': 0}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

# ── Main scan ───────────────────────────────────────────────────────────────────
def do_scan(balance_override=None):
    wallets = load_wallets()
    if not wallets:
        log.warning('No wallet data yet — skipping scan')
        return None

    wr100 = filter_100wr(wallets)
    positions = get_positions(wr100)
    if not positions:
        return None

    top1 = select_top_n(positions, 1)
    top2 = select_top_n(positions, 2)

    state = load_state()
    balance = balance_override if balance_override is not None else state['balance']

    # TOP-1
    t1 = top1[0] if top1 else None
    if t1 and not is_cooldown(t1['wallet'], t1['mult']):
        card = format_top1(t1, balance, FRAC_TOP1)
        ok = send(card, 'hub')
        log.info(f'TOP-1 sent: mult={t1["mult"]:.4f} | size=${balance*FRAC_TOP1:.2f}')
        # Save to state
        state['trades'].append({'ts': datetime.now(timezone.utc).isoformat(), 'top': 1, **t1})
        save_state(state)
        return {'top': 1, 'trade': t1, 'balance': balance, 'sent': ok}

    # TOP-2
    if len(top2) >= 2 and not is_cooldown(top2[1]['wallet'], top2[1]['mult']):
        card = format_top2(top2, balance, FRAC_TOP2_TOTAL, TOP_N)
        ok = send(card, 'hub')
        log.info(f'TOP-2 sent: mults={[t["mult"] for t in top2]}')
        return {'top': 2, 'trades': top2, 'balance': balance, 'sent': ok}

    return None

# ── Daemon loop ────────────────────────────────────────────────────────────────
def run_daemon(scan_interval=SCAN_INTERVAL):
    log.info(f'Fast-Scan daemon started — polling every {scan_interval}s')
    while True:
        try:
            result = do_scan()
            if result:
                log.info(f"Scan complete: Top-{result['top']} signal sent")
            else:
                log.debug("Scan complete: no new signals")
        except Exception as e:
            log.error(f'Scan error: {e}')
        time.sleep(scan_interval)

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Fast-scan daemon')
    parser.add_argument('--once', action='store_true', help='Run single scan and exit')
    parser.add_argument('--daemon', action='store_true', help='Run continuously')
    parser.add_argument('--interval', type=int, default=SCAN_INTERVAL, help='Scan interval seconds')
    args = parser.parse_args()

    if args.once:
        result = do_scan()
        if result:
            print(f"✅ Fast scan: Top-{result['top']} signal sent")
        else:
            print("⏳ No new signals this cycle")
    elif args.daemon:
        run_daemon(args.interval)
    else:
        # Default: run once
        result = do_scan()
        if result:
            print(f"✅ Fast scan: Top-{result['top']} signal sent")
        else:
            print("⏳ No new signals this cycle")