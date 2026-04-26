#!/usr/bin/env python3
"""
WhaleTrax Alert Watcher – v2
Scans for new big wins on Polymarket and broadcasts to Polyshark channel.
Deduplicates by (market_id + wallet) across runs.
Rate-limited to MAX_ALERTS_PER_RUN to avoid flooding.
"""

import sys, os, json, time, logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/repos/whaletrax')
os.chdir('/home/ubuntu/.openclaw/workspace/repos/whaletrax')

from dotenv import load_dotenv
load_dotenv()

import requests
from src import config, big_win_detector as bwd
from polyshark_sender import test_connection

# ── Config ────────────────────────────────────────────────────────────────────
STATE_FILE     = Path('/tmp/whaletrax_alert_state.json')
LOG_FILE       = Path('/tmp/whaletrax_watcher.log')
CRED_FILE      = Path('/home/ubuntu/.openclaw/workspace/credentials/skey-telegram-jefe-swarm2bot')
MAX_ALERTS_RUN = 5          # max alerts per run to avoid flooding
POLL_TOP_N     = 20         # leaderboard wallets to scan
MIN_PROFIT     = 500        # USD
MIN_ROI        = 50         # percent
MIN_SIZE       = 100         # USD cost basis

# Read bot token
def _load_token():
    if CRED_FILE.exists():
        for line in CRED_FILE.read_text().strip().split('\n'):
            if '=' in line:
                k, v = line.split('=', 1)
                if k in ('TOKEN', 'BOT_TOKEN', 'WHALETRAX_BOT_TOKEN'):
                    return v.strip()
    return os.getenv('WHALETRAX_BOT_TOKEN', '8741871021:AAF_OJ0rkE5T_bq4YXT_RPUwWG07bYs8I3g')

TOKEN   = _load_token()
CHAT_ID = '-1003999194095'

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger('whaletrax_watcher')

# ── State ─────────────────────────────────────────────────────────────────────
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {'seen_keys': [], 'last_run': None, 'total_sent': 0}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

# ── Telegram send ────────────────────────────────────────────────────────────
def send_telegram(text: str) -> bool:
    try:
        r = requests.post(
            f'https://api.telegram.org/bot{TOKEN}/sendMessage',
            json={'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'Markdown'},
            timeout=15
        )
        ok = r.json().get('ok', False)
        if ok:
            log.info('Alert sent ✓')
        else:
            log.error(f'Telegram error: {r.json()}')
        return ok
    except Exception as e:
        log.error(f'Failed to send: {e}')
        return False

# ── Build alert text ─────────────────────────────────────────────────────────
def format_big_win_alert(bw) -> str:
    emoji = '🟢'
    question = bw.market_question or 'Unknown Market'
    return f"""{emoji} *WHALE WIN DETECTED*
━━━━━━━━━━━━━━━━━━
📊 *{question[:80]}*
━━━━━━━━━━━━━━━━━━
💰 Profit: ${bw.profit_usdc:,.0f} | ROI: {bw.roi_pct:.0f}%
📦 Position: ${bw.trade_size_usdc:,.0f}
━━━━━━━━━━━━━━━━━━
🐋 Trader: `{bw.display_name or 'Anonymous Whale'}`
📍 Wallet: `{bw.wallet[:20]}...`
━━━━━━━━━━━━━━━━━━
🔗 https://polymarket.com/event/{bw.market_id}"""

# ── Main watcher ──────────────────────────────────────────────────────────────
def run():
    state    = load_state()
    seen     = set(state.get('seen_keys', []))
    log.info('=== WhaleTrax Watcher Run ===')

    # Apply thresholds
    config.BIG_WIN_MIN_PROFIT_USDC     = MIN_PROFIT
    config.BIG_WIN_MIN_ROI_PCT         = MIN_ROI
    config.BIG_WIN_MIN_TRADE_SIZE_USDC  = MIN_SIZE

    # Poll big wins
    try:
        big_wins = bwd.scan_big_wins_from_leaderboard(top_n=POLL_TOP_N)
        log.info(f'Polled {len(big_wins)} total big wins from top-{POLL_TOP_N} wallets')
    except Exception as e:
        log.error(f'Polling error: {e}')
        return

    # Filter to NEW only, sort by profit desc
    new_wins = [bw for bw in big_wins
                if f"{bw.market_id}_{bw.wallet}" not in seen]
    new_wins.sort(key=lambda bw: bw.profit_usdc, reverse=True)
    new_wins = new_wins[:MAX_ALERTS_RUN]  # rate limit

    log.info(f'New wins this run: {len(new_wins)}')

    sent = 0
    for bw in new_wins:
        key = f"{bw.market_id}_{bw.wallet}"
        text = format_big_win_alert(bw)
        if send_telegram(text):
            seen.add(key)
            state['total_sent'] = state.get('total_sent', 0) + 1
            sent += 1

    state['seen_keys'] = list(seen)[-500:]  # keep last 500 to prevent unbounded growth
    state['last_run']  = datetime.now().isoformat()
    save_state(state)

    log.info(f'Done. Sent {sent} new alerts. Total ever sent: {state["total_sent"]}')
    return sent

# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == '__main__':
    if '--test' in sys.argv:
        log.info('Testing connection...')
        ok = test_connection()
        sys.exit(0 if ok else 1)
    run()
