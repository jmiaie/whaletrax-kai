#!/usr/bin/env python3
"""
WhaleTrax Alert Watcher - v2
Scans for new big wins on Polymarket and broadcasts to Polyshark channel.
Deduplicates by (market_id + wallet) across runs.
Rate-limited to MAX_ALERTS_PER_RUN to avoid flooding.

Controls:
  --pause      Suspend scanning (sets pause flag, exits immediately)
  --resume     Remove pause flag, re-enable scanning
  --inject     Inject a simulated big-win alert (testing, no scan)
  --stop       Clear all state (seen_keys, total_sent) and exit
  --status     Print current pause/run state and counters
  --test       Test Telegram connection and exit
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

JARV_EMOJI = '\U000026A1'  # ⚡

# Config
STATE_FILE     = Path('/tmp/whaletrax_alert_state.json')
PAUSE_FILE     = Path('/tmp/whaletrax_paused.flag')
LOG_FILE       = Path('/tmp/whaletrax_watcher.log')
CRED_FILE      = Path('/home/ubuntu/.openclaw/workspace/credentials/skey-telegram-jefe-swarm2bot')
MAX_ALERTS_RUN = 5
POLL_TOP_N     = 20
MIN_PROFIT     = 500
MIN_ROI        = 50
MIN_SIZE       = 100

def _load_token():
    if CRED_FILE.exists():
        for line in CRED_FILE.read_text().strip().split('\n'):
            if '=' in line:
                k, v = line.split('=', 1)
                if k in ('TOKEN', 'BOT_TOKEN', 'WHALETRAX_BOT_TOKEN'):
                    return v.strip()
    return os.getenv('WHALETRAX_BOT_TOKEN', '8678199814:AAECmOod8cH3GqKqgKnc7NdcmR1bAif2BBg')

TOKEN   = _load_token() or '8678199814:AAECmOod8cH3GqKqgKnc7NdcmR1bAif2BBg'
CHAT_ID = '-1003786930778'

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger('whaletrax_watcher')

# Controls
def is_paused() -> bool:
    return PAUSE_FILE.exists()

def pause():
    PAUSE_FILE.write_text(json.dumps({
        'paused_at': datetime.now().isoformat(),
        'paused_by': 'manual',
    }))
    log.info(f'{JARV_EMOJI} Scanner PAUSED')

def resume():
    if PAUSE_FILE.exists():
        PAUSE_FILE.unlink()
        log.info(f'{JARV_EMOJI} Scanner RESUMED')
    else:
        log.info(f'{JARV_EMOJI} Scanner was not paused')

def stop():
    state = load_state()
    seen_count = len(state.get('seen_keys', []))
    total = state.get('total_sent', 0)
    STATE_FILE.write_text(json.dumps({'seen_keys': [], 'last_run': None, 'total_sent': 0}))
    if PAUSE_FILE.exists():
        PAUSE_FILE.unlink()
    log.info(f'{JARV_EMOJI} Scanner STOPPED - cleared {seen_count} seen_keys, total_sent was {total}')

def status():
    state = load_state()
    p = 'PAUSED' if is_paused() else 'RUNNING'
    total = state.get('total_sent', 0)
    seen = len(state.get('seen_keys', []))
    last = state.get('last_run', 'never')
    print(f'{JARV_EMOJI} WhaleTrax Watcher - [{p}]')
    print(f'  Total alerts ever sent: {total}')
    print(f'  Seen keys in memory:    {seen}')
    print(f'  Last run:              {last}')
    if is_paused():
        info = json.loads(PAUSE_FILE.read_text())
        print(f'  Paused at:             {info.get("paused_at")}')

# State
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {'seen_keys': [], 'last_run': None, 'total_sent': 0}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))

# Telegram send
def send_telegram(text: str) -> bool:
    try:
        r = requests.post(
            f'https://api.telegram.org/bot{TOKEN}/sendMessage',
            json={'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'Markdown'},
            timeout=15
        )
        ok = r.json().get('ok', False)
        if ok:
            log.info(f'{JARV_EMOJI} Alert sent')
        else:
            log.error(f'Telegram error: {r.json()}')
        return ok
    except Exception as e:
        log.error(f'Failed to send: {e}')
        return False

# Build alert text
def format_big_win_alert(bw) -> str:
    question = bw.market_question or 'Unknown Market'
    return f"""{JARV_EMOJI} *WHALE WIN DETECTED*
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

# Inject
def inject_fake_alert():
    class FakeBW:
        market_id = 'inject-test-001'
        wallet = '0xINJECTEDFAKEWALLET1234567890'
        display_name = 'INJECT TEST'
        market_question = 'INJECT TEST - Scanner controls operational'
        profit_usdc = 99999
        roi_pct = 999
        trade_size_usdc = 5000
    text = format_big_win_alert(FakeBW())
    ok = send_telegram(text)
    result = 'OK' if ok else 'FAIL'
    print(f'{JARV_EMOJI} Inject test: {result}')
    return ok

# Main watcher
def run():
    if is_paused():
        log.info(f'{JARV_EMOJI} Scanner is PAUSED - exiting (use --resume to re-enable)')
        print(f'{JARV_EMOJI} Scanner is paused. Run with --resume to re-enable.')
        sys.exit(0)

    state    = load_state()
    seen     = set(state.get('seen_keys', []))
    log.info(f'{JARV_EMOJI} === WhaleTrax Watcher Run ===')

    config.BIG_WIN_MIN_PROFIT_USDC     = MIN_PROFIT
    config.BIG_WIN_MIN_ROI_PCT         = MIN_ROI
    config.BIG_WIN_MIN_TRADE_SIZE_USDC  = MIN_SIZE

    try:
        big_wins = bwd.scan_big_wins_from_leaderboard(top_n=POLL_TOP_N)
        log.info(f'{JARV_EMOJI} Polled {len(big_wins)} total big wins from top-{POLL_TOP_N} wallets')
    except Exception as e:
        log.error(f'Polling error: {e}')
        return

    new_wins = [bw for bw in big_wins
                if f"{bw.market_id}_{bw.wallet}" not in seen]
    new_wins.sort(key=lambda bw: bw.profit_usdc, reverse=True)
    new_wins = new_wins[:MAX_ALERTS_RUN]

    log.info(f'{JARV_EMOJI} New wins this run: {len(new_wins)}')

    sent = 0
    for bw in new_wins:
        key = f"{bw.market_id}_{bw.wallet}"
        text = format_big_win_alert(bw)
        if send_telegram(text):
            seen.add(key)
            state['total_sent'] = state.get('total_sent', 0) + 1
            sent += 1

    state['seen_keys'] = list(seen)[-500:]
    state['last_run']  = datetime.now().isoformat()
    save_state(state)

    log.info(f'{JARV_EMOJI} Done. Sent {sent} new alerts. Total ever sent: {state["total_sent"]}')
    return sent

# Entry point
if __name__ == '__main__':
    if '--pause' in sys.argv:
        pause()
    elif '--resume' in sys.argv:
        resume()
    elif '--stop' in sys.argv:
        stop()
    elif '--status' in sys.argv:
        status()
    elif '--inject' in sys.argv:
        inject_fake_alert()
    elif '--test' in sys.argv:
        log.info(f'{JARV_EMOJI} Testing connection...')
        ok = test_connection()
        sys.exit(0 if ok else 1)
    else:
        run()