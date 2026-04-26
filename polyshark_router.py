#!/usr/bin/env python3
"""
Polyshark Alert Router v3
Sequential distribution:
  1. ONE card to PolysharkPro immediately
  2. Cron job fires 5-10 min later → copies to category channel(s)
  3. Queue fires 6 hr later → copies to Polyshark (free)
Deduplicated by (market_id + wallet). Max 5 new alerts per run.
"""
import sys, os, json, logging, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/repos/whaletrax')
os.chdir('/home/ubuntu/.openclaw/workspace/repos/whaletrax')
import requests
from src import config, big_win_detector as bwd, polymarket_client as pm
from polyshark_memory import ingest_alert, ingest_fault, ingest_whale, ingest_streak, ingest_rank_change, ingest_market

STATE_FILE  = Path('/tmp/polyshark_router_state.json')
QUEUE_FILE  = Path('/tmp/polyshark_router_queue.json')
LOG_FILE    = Path('/tmp/polyshark_router.log')
PAUSE_FILE  = Path('/tmp/polyshark_router_paused')  # anti-spam killswitch
MAX_PER_RUN = 5
MAX_SENDS_PER_CYCLE = 12   # hard cap on total sends per cycle (PRO + category + free)
POLL_TOP_N  = 20
FREE_DELAY   = timedelta(minutes=90)
CURATED_DELAY = timedelta(minutes=15)
MAX_CURATED  = 4
CAT_DELAY    = timedelta(minutes=10)
PRO_DELAY    = timedelta(minutes=3)
SEND_PAUSE   = 45
MIN_PROFIT   = 500
MIN_ROI      = 50
MIN_SIZE     = 100

# Per-cycle send tracking (resets each run)
_cycle_sends = 0
_cycle_rl_errors = 0

TOKEN = '8741871021:AAH_ZeMzvMhQxPnx-Z2R_S5asnLCwlHsxa0'

CHANNELS = {
    'hub':      -1003786930778,  # Alert Hub (Kai receives first)
    'sports':   -1003948034686,
    'crypto':   -1003999731708,
    'weather':  -1003532326443,
    'world':    -1003927756388,
    'politics': -1003935178097,
    'econ':     -1003868008293,
    'esports':  -1003700788085,  # PolysharkEsports
    'free':     -1003999194095,
}
CHANNEL_NAMES = {v: k for k, v in CHANNELS.items()}

CRYPTO_KW    = ['bitcoin','btc','ethereum','eth','crypto','solana','dogecoin','coin','nft']
SPORTS_KW    = [
    # Leagues
    'nba','nfl','nhl','mlb','nba finals','nfl draft','nhl playoffs','mlb world series',
    'soccer','football','basketball','tennis','hockey','rugby','cricket','golf','formula 1',
    'march madness','super bowl','world series','stanley cup','nba draft','bowl game',
    'college football','college basketball','grand slam','championship','playoffs','finals',
    'all-star','world cup','euro cup','fa cup','champions league',
    # NBA teams
    'hawks','celtics','nets','hornets','bulls','cavs','cavaliers','mavericks','nuggets',
    'pistons','warriors','dubs','rockets','pacers','clippers','lakers','grizzlies','heat',
    'bucks','wolves','t-wolves','pelicans','knicks','thunder','okc thunder','magic','sixers',
    'suns','blazers','kings','spurs','raptors','jazz','wizards',
    # NFL teams
    'cardinals','falcons','ravens','bills','panthers','bears','bengals','browns','cowboys',
    "boys",'broncos','lions','packers','texans','colts','jaguars','jags','chiefs','kc chiefs',
    'raiders','lv raiders','chargers','la chargers','rams','dolphins','vikings','patriots',
    'pats','saints','giants','ny giants','jets','ny jets','eagles','steelers','niners','49ers',
    'seahawks','buccaneers','bucs','titans','commanders','washington',
    # NHL teams
    'ducks','bruins','sabres','flames','hurricanes','blackhawks','avalanche','blue jackets',
    'stars','red wings','oilers','kings','la kings','wild','canadiens','habs','predators',
    'devils','islanders','rangers','flyers','penguins','kraken','blues','lightning','maple leafs',
    'leafs','utah hc','uhc','canucks','golden knights','knights','capitals','jets',
    # MLB teams
    'diamondbacks','dbacks','braves','orioles','red sox','cubs','white sox','reds','guardians',
    'rockies','tigers','astros','royals','angels','la angels','dodgers','marlins','brewers',
    'twins','mets','yankees','yanks','athletics',"a's",'phillies','pirates','padres','giants',
    'mariners','cardinals','rays','rangers','blue jays','nationals',
    # Soccer clubs
    'gunners','villans','bees','seagulls','clarets','blues','toffees','cottagers','reds',
    'man city','citizens','man utd','red devils','magpies','forest','lilywhites','hammers',
    'wolverhampton','barca','barcelona','los blancos','rojiblancos','bayern','bvb',
    'nerazzurri','rossoneri','juve','old lady','bhoys','gers',
    # NCAA Football
    'crimson tide','tide','buckeyes','bulldogs','dogs','longhorns','sooners','nittany lions',
    'fighting irish','irish','volunteers','vols','hurricanes','trojans','rebels','aggies',
    'seminoles','huskies','beavers','cougars','bruins',
    # NCAA Basketball
    'blue devils','wildcats','jayhawks','tar heels','unc','spartans','boilermakers',
    # Tennis
    'australian open','oz open','roland Garros','wimbledon','sw19','usta','us open',
    'djokovic','nole','nadal','rafa','federer','alcaraz','sinner','sabalenka','swiatek',
    # Golf
    'masters','augusta','usga','pga championship','british open','royal liverpool',
    # F1
    'red bull','rbr','ferrari','scuderia','mercedes','brackley','mclaren','papaya',
    'aston martin','amr','alpine','renault','haas','sauber','alphatauri','rb f1',
    # Generic city/team names that appear in sports contexts
    'porsche','grand prix','senators','edmonton','vegas','toronto','boston','miami',
    'dallas','houston','chicago','philadelphia','detroit','phoenix','seattle','montreal',
    'calgary','vancouver','pittsburgh','tampa','baylor','duke','kentucky','alabama',
    'ohio state','georgia','lsu','michigan','oklahoma','ncaa','ncaaf','ncaab',
]

ESPORTS_KW    = [
    'esports','cs2','csgo','valorant','league of legends','lol:','lck','lol worlds',
    'dota 2','rocket league','call of duty','the international','worlds','champions',
    'blast','iem','esl','epic games','riot games','blizzard','g2','faze','navi',
    'sentinels','cloud9','c9','100 thieves','100t','fnatic','team liquid','liquid',
    'drx','paper rex','prx','loud','optics','evil geniuses','eg','heroic','ence',
    'complexity','big','nip','og','mibr','furia','imperial','spirit','virtus.pro',
    't1','faker','geng','jdg','jd gaming','blg','tes','rogue','golden guardians',
    'dk','dplus kia','lsb','sandbox','freecs','team spirit','secret','nigma',
    'tundra','gaimin gladiators','betboom','seoul dynasty','shanghai dragons','nyxl',
    'valiant','guangzhou charge','fusion','mayette','mayhem','outlaws','spitfire',
    'defiant','uprising','reign','fuel','gladiators','vanguard','seoul infernal',
    'bds','nrg','moist','giants','renault vitalite','atlanta faze','optic texas',
    'thieves','subliners','ultra','surge','rokr','valorant champions','esports event',
    'esports tournament','overwatch',
]
# Context anchors: a sports market must contain at least one of these words
# along with a team name to prevent false positives like "Celtic knots" or "Kings of Leon"
SPORTS_ANCHOR_KWS = {'vs', 'v', 'game', 'win', 'loss', 'score', 'playoff', 'season',
                     'championship', 'match', 'nba', 'nfl', 'nhl', 'mlb', 'ncaa',
                     'finals', 'semifinal', 'round', 'cup', 'tournament', 'league',
                     'soccer', 'football', 'basketball', 'hockey', 'tennis', 'golf',
                     'over/under', 'spread', 'moneyline', 'record', 'standings'}

WEATHER_KW   = ['weather','rain','snow','storm','temperature','climate','flood','tornado',
                 'heat wave','cold wave','tropical','monsoon','blizzard','drought','cyclone','typhoon','hurricane ']
POLITICS_KW  = ['election','trump','biden','congress','senate','vote','political','republican',
                 'democrat','parliament','president','governor','supreme court']
WORLD_KW     = ['world','global','international','war','g7','g20','oil','geopolitical']
ECON_KW      = ['gdp','inflation','fed','rate','interest','recession','economy','unemployment']

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s',
                    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()])
log = logging.getLogger('polyshark_router')

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {'seen_keys': [], 'total_sent': 0, 'curated_sent': 0}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state))

def load_queue():
    if QUEUE_FILE.exists():
        try:
            return json.loads(QUEUE_FILE.read_text())
        except Exception:
            pass
    return []

def save_queue(q):
    QUEUE_FILE.write_text(json.dumps(q, indent=2))

def send(cid, text, pause=True):
    """Send Telegram message. Killswitch + rate-limit + per-cycle hard cap."""
    global _cycle_sends, _cycle_rl_errors
    if PAUSE_FILE.exists():
        log.warning('Router PAUSED — killswitch active (touch /tmp/polyshark_router_paused to resume)')
        return False
    if _cycle_sends >= MAX_SENDS_PER_CYCLE:
        log.warning(f'Hard cap reached ({MAX_SENDS_PER_CYCLE} sends/cycle) — skipping this send')
        return False
    if pause and hasattr(send, '_last_send') and send._last_send:
        elapsed = time.time() - send._last_send
        if elapsed < 0.035:
            time.sleep(0.035 - elapsed)
    try:
        r = requests.post(f'https://api.telegram.org/bot{TOKEN}/sendMessage',
            json={'chat_id': cid, 'text': text, 'parse_mode': 'HTML',
                  'disable_web_page_preview': True}, timeout=15)
        send._last_send = time.time()
        ok = r.json().get('ok', False)
        if not ok:
            err = r.json().get('description', 'unknown')
            if 'Too Many Requests' in err:
                _cycle_rl_errors += 1
                log.warning(f'Rate limit hit (cycle #{_cycle_rl_errors}): {err}')
            else:
                log.warning(f'Send failed {cid}: {err}')
                ingest_fault('send_fail', err, {'chat_id': str(cid)})
        if ok:
            _cycle_sends += 1
        return ok
    except Exception as e:
        log.error(f'Send error {cid}: {e}')
        ingest_fault('send_exception', str(e), {'chat_id': str(cid)})
        return False

send._last_send = 0.0

def detect_categories_with_confidence(question: str):
    """
    Return (cats, best_cat) where cats=all matched categories and best_cat=single highest confidence.
    Uses SPORTS_ANCHOR_KWS to prevent false positives on team names in non-sports contexts.
    """
    q = question.lower()
    scores = {}
    for cat, kws in [
        ('sports',   SPORTS_KW),
        ('esports',  ESPORTS_KW),
        ('crypto',   CRYPTO_KW),
        ('weather',  WEATHER_KW),
        ('politics', POLITICS_KW),
        ('world',    WORLD_KW),
        ('econ',     ECON_KW),
    ]:
        score = sum(1 for kw in kws if kw in q)
        if cat == 'sports' and score > 0:
            # Physical sports require a context anchor to prevent false positives (e.g., "Celtic knots")
            has_anchor = any(a in q for a in SPORTS_ANCHOR_KWS)
            if not has_anchor:
                score = 0
        # Esports does NOT need anchor — team/org names are inherently esports context
        if score > 0:
            scores[cat] = score
    if not scores:
        return (['pro'], 'pro')
    # Minimum confidence threshold: if best score <= 2, skip category (send PRO-only)
    if max(scores.values()) <= 2:
        return (['pro'], 'pro')
    best_cat = max(scores, key=scores.get)
    return (list(scores.keys()), best_cat)

def detect_categories(q):
    q = q.lower()
    cats = []
    if any(k in q for k in CRYPTO_KW):   cats.append('crypto')
    if any(k in q for k in SPORTS_KW):    cats.append('sports')
    if any(k in q for k in ESPORTS_KW):   cats.append('esports')
    if any(k in q for k in WEATHER_KW):   cats.append('weather')
    if any(k in q for k in POLITICS_KW):  cats.append('politics')
    if any(k in q for k in WORLD_KW):     cats.append('world')
    if any(k in q for k in ECON_KW):       cats.append('econ')
    return cats if cats else ['pro']

def format_card(bw, tier='PRO'):
    """
    v1.2 card format — Jeff Milam, Polyshark 2026-04-25

    Emoji rules:
      💵 = trade SIZE (not 💳)
      🐋 = wallet address (not 👤)
      ⛓️ = links (not 🧭)
      🏅 = inline badge with question line (not separate)
      🏆 🟢 = green badge WR ≥65%
      🏆 🟠 = amber badge WR 45-64%
      🏆 🔴 = red badge WR <40%
      n=N = trade count
      ✅ $X | ✅ +X% ROI = profit + ROI both green
      💰 $X | 💲 -X% ROI = loss + negative ROI both red

    Reject rules:
      Entry price $0.0000 → REJECT (return None)
      Stock tickers ($AMAZON, $YELLEN, $MSFT etc) → REJECT (return None)
      Resolved markets older than 2025 → REJECT (return None)
    """
    import datetime as dt

    # ── REJECT: $0.0000 entry price ────────────────────────────────────────
    entry_px = getattr(bw, 'avg_price', 0)
    if entry_px == 0 or entry_px is None:
        log.warning(f"REJECTED: $0.0000 entry price market {getattr(bw,'market_id','')}")
        return None

    # ── REJECT: stock tickers ──────────────────────────────────────────────
    q_lower = getattr(bw, 'market_question', '').lower()
    STOCK_TICKERS = ['$amazon','$yellen','$msft','$aapl','$googl','$meta','$tsla',
                     '$nvda','$amzn','$fb','$spam','$musk','$zuck','$spx','$spy']
    for ticker in STOCK_TICKERS:
        if ticker in q_lower:
            log.warning(f"REJECTED: stock ticker in market: {getattr(bw,'market_id','')}")
            return None

    # ── REJECT: pre-2025 resolved markets ──────────────────────────────────
    end_date_str = getattr(bw, 'end_date', '') or ''
    if len(end_date_str) >= 4:
        try:
            year = int(end_date_str[:4])
            if year < 2025:
                log.warning(f"REJECTED: pre-2025 resolved market {getattr(bw,'market_id','')} year={year}")
                return None
        except ValueError:
            pass  # no year readable, allow it

    # ── Build card ───────────────────────────────────────────────────────────
    free_card = (tier == 'free')
    label     = 'FREE TEASER' if free_card else tier.upper()

    # Header with 🏅 inline
    header = f'<b>🟢 WHALE WIN [{label}] 🏅</b>'

    # Market question — truncate at 72 chars
    q = getattr(bw, 'market_question', '?')[:72]
    market = f'<b>🏅 {q}</b>'

    # Direction
    direction = getattr(bw, 'outcome', '') or ''
    if direction.upper().startswith(('DOWN', 'NO')):
        bet = f'<b>🎯 ⬇️ BET DOWN on {direction}</b>'
    else:
        bet = f'<b>🎯 ⬆️ BET UP on {direction}</b>' if direction else '<b>🎯 ⬆️ BET UP</b>'

    # ── Profit / ROI — both green or both red ────────────────────────────
    profit_usdc = getattr(bw, 'profit_usdc', 0) or 0
    roi_pct     = getattr(bw, 'roi_pct', 0) or 0
    if profit_usdc >= 0:
        profit = f'✅ <b>${profit_usdc:,.0f}</b> | <b>✅ +{roi_pct:.0f}% ROI</b>'
    else:
        profit = f'💰 <b>${profit_usdc:,.0f}</b> | <b>💲 {roi_pct:.0f}% ROI</b>'

    # ── Trade SIZE (💵 not 💳) and entry price ─────────────────────────────
    size = getattr(bw, 'trade_size_usdc', 0) or 0
    pct_px = f'{entry_px*100:.1f}¢'
    size_line = f'💵 ${size:,.0f} position | Entry: {pct_px}'

    # ── Win rates with color badges ─────────────────────────────────────────
    n_trades = getattr(bw, 'total_positions', 0) or 0
    wr_lt    = getattr(bw, 'win_rate', 0) or 0
    wr_30    = getattr(bw, 'win_rate_30d', 0) or 0

    def wr_badge(wr_val):
        if wr_val >= 65:  return '🏆 🟢', f'{wr_val:.0f}%'
        if wr_val >= 45:  return '🏆 🟠', f'{wr_val:.0f}%~'
        if wr_val > 0:    return '🏆 🔴', f'{wr_val:.0f}-%'
        return '', ''

    lt_badge, lt_str = wr_badge(wr_lt)
    wr30_badge, wr30_str = wr_badge(wr_30)

    if wr_lt > 0:
        if wr_30 > 0:
            wr = f'{lt_badge} {lt_str} lifetime WR   {wr30_badge} | {wr30_str} 30d WR  (n={n_trades})'
        else:
            wr = f'{lt_badge} {lt_str} lifetime WR  (n={n_trades})'
    else:
        wr = ''

    # ── Streak ───────────────────────────────────────────────────────────────
    streak = getattr(bw, 'win_streak', 0) or 0
    if streak >= 8:
        streak_badge = '🔥🔥 ON FIRE 🔥🔥'
    elif streak >= 5:
        streak_badge = f'🔥 {streak}-win streak'
    else:
        streak_badge = ''

    # ── Wallet label (🐋 not 👤) ────────────────────────────────────────────
    trader = f'🐋 {_whale_label(bw.wallet, bw.display_name)}'

    # ── Polymarket link (⛓️ not 🧭) ────────────────────────────────────────
    market_id = getattr(bw, 'market_id', '') or ''
    link = f'⛓️ https://polymarket.com/event/{market_id}'

    # ── Dates + wallet % of leaderboard ─────────────────────────────────────
    trade_ts   = getattr(bw, 'timestamp', None)
    trade_date = dt.datetime.fromtimestamp(trade_ts, tz=dt.timezone.utc).strftime('%b %d %Y') if trade_ts else '?'
    end_date   = end_date_str[:10] if end_date_str else '?'
    vol        = getattr(bw, 'leaderboard_volume', 0) or 0
    wallet_pct = f' ({size / vol * 100:.1f}% of wallet)' if vol and vol > 0 else ''
    dates      = f'📅 Opened: {trade_date} | Resolved: {end_date}{wallet_pct}'

    # ── Assemble ─────────────────────────────────────────────────────────────
    sep = '——————————'
    if free_card:
        lines = [header, sep, market, sep, profit, size_line, bet, dates, sep, link]
    else:
        lines = [header, sep, market, sep, profit, size_line, bet, dates]
        if wr:       lines.append(wr)
        if streak_badge: lines.append(streak_badge)
        lines += [sep, trader, link]
    return '\n'.join(lines) + '\n'





def process_queue(state):
    """Fire category forwards (7 min) and free forwards (6 hr)."""
    queue = load_queue()
    if not queue:
        return
    now = datetime.now(timezone.utc)
    updated = []
    for item in queue:
        queued_at = datetime.fromisoformat(item['queued_at']).replace(tzinfo=timezone.utc)
        cat_ready  = (now - queued_at) >= CAT_DELAY
        free_ready = (now - queued_at) >= FREE_DELAY
        pro_ready  = (now - queued_at) >= PRO_DELAY

        # Pro channel — fire once when ready (3-min delay)
        if pro_ready and not item.get('pro_sent'):
            send(CHANNELS['hub'], format_card(bw_from_item(item), 'pro'))
            log.info(f'PRO delay fired: {item["question"][:40]}')
            item['pro_sent'] = True

        # Category channel — fire once when ready to the HIGHEST CONFIDENCE category
        if cat_ready and item.get('cat_sent') != item['cats']:
            cats = item['cats']
            best_cat = item.get('best_cat', 'pro')
            if best_cat and best_cat != 'pro':
                cid = CHANNELS.get(best_cat)
                if cid:
                    # Calculate and log confidence score for QA
                    q = item['question'].lower()
                    score = sum(1 for kw in SPORTS_KW if kw in q) if best_cat == 'sports' else \
                            sum(1 for kw in ESPORTS_KW if kw in q) if best_cat == 'esports' else \
                            sum(1 for kw in CRYPTO_KW if kw in q) if best_cat == 'crypto' else \
                            sum(1 for kw in WEATHER_KW if kw in q) if best_cat == 'weather' else \
                            sum(1 for kw in POLITICS_KW if kw in q) if best_cat == 'politics' else \
                            sum(1 for kw in WORLD_KW if kw in q) if best_cat == 'world' else \
                            sum(1 for kw in ECON_KW if kw in q) if best_cat == 'econ' else 0
                    send(cid, format_card(bw_from_item(item), best_cat))
                    log.info(f'Category forward ({best_cat}) [score={score}]: {item["question"][:40]}')
            item['cat_sent'] = item['cats']

        # Free channel — fire when ready (15 min for curated, 90 min for others)
        curated_ready = (now - queued_at) >= CURATED_DELAY
        free_ready    = (now - queued_at) >= FREE_DELAY
        item_ready    = curated_ready if item.get('is_curated') else free_ready

        if item_ready and not item.get('free_sent'):
            if item.get('is_curated'):
                # Send FULL PRO card to free tier (conversion hook — user sees full value)
                send(CHANNELS['free'], format_card(bw_from_item(item), 'pro'))
                log.info(f'★ CURATED FREE sent: {item["question"][:40]}')
            else:
                send(CHANNELS['free'], format_card(bw_from_item(item), 'free'))
                log.info(f'FREE delay fired: {item["question"][:40]}')
            state['total_sent'] += 1
            item['free_sent'] = True
            continue  # drop from queue

        updated.append(item)

    if len(updated) < len(queue):
        save_queue(updated)

def bw_from_item(item):
    """Reconstruct a minimal object from queued item for formatting."""
    import json as _json
    class BW:
        def __init__(self, d):
            self.market_question = d.get('question','')
            self.market_id        = d.get('market_id','')
            self.wallet           = d.get('wallet','')
            self.profit_usdc      = d.get('profit_usdc', 0)
            self.roi_pct          = d.get('roi_pct', 0)
            self.trade_size_usdc  = d.get('trade_size_usdc', 0)
            self.display_name     = d.get('display_name', '')
            self.timestamp        = d.get('timestamp')   # FIX: was None
            self.leaderboard_volume = d.get('leaderboard_volume', 0)
            self.outcome          = d.get('outcome','')
            self.end_date         = d.get('end_date','')
            self.avg_price        = d.get('avg_price', 0)
            self.is_curated       = d.get('is_curated', False)

            # Look up wallet profile for real win rate / streak / trade count
            wp_path = Path('/tmp/wallet_profiles.json')
            if wp_path.exists():
                try:
                    wps = _json.loads(wp_path.read_text())
                    waddr = (self.wallet or '').lower()
                    if waddr in wps:
                        wp = wps[waddr]
                        self.win_rate         = wp.get('win_rate', 0) or 0
                        self.win_rate_30d     = wp.get('win_rate_30d', 0) or 0
                        self.total_positions  = wp.get('total_positions', 0) or 0
                        self.win_streak       = wp.get('current_streak', 0) or 0
                        return
                except Exception:
                    pass

            # Fallback: from item itself (or 0)
            self.win_rate         = d.get('win_rate', 0)
            self.win_rate_30d     = d.get('win_rate_30d', 0)
            self.total_positions = d.get('total_positions', 0)
            self.win_streak      = d.get('win_streak', 0)

    return BW(item)


def _is_curated_pick(bw, state):
    """Return True if this big win qualifies as a curated pick (top 3-4 per session)."""
    if state.get('curated_sent', 0) >= MAX_CURATED:
        return False
    # Criteria: ROI >= 100% OR profit >= $10K OR win_streak >= 5 OR top 3 by profit in scan
    if bw.roi_pct >= 100:
        return True
    if bw.profit_usdc >= 10000:
        return True
    if getattr(bw, 'win_streak', 0) >= 5:
        return True
    return False


WATCH_WALLET = '0x63a51cbb37341837b873bc29d05f482bc2988e33'.lower()
WATCH_LABEL  = '\U0001f3c6 HIGH-FREQ WINNING WHALE \U0001f3c6'

def _whale_label(wallet, display_name):
    if wallet and wallet.lower() == WATCH_WALLET:
        return WATCH_LABEL
    return display_name or 'Anonymous Whale'

LB_STATE_FILE = Path('/tmp/whaletrax_lb_rank_state.json')

def _check_leaderboard_changes():
    try:
        entries = pm.get_leaderboard(limit=20)
        lb = {str(e.get('proxyWallet','')).lower(): {'rank': int(e.get('rank',0)), 'vol': float(e.get('vol',0)), 'name': e.get('userName','')} for e in entries if e.get('proxyWallet')}
        prev_raw = json.loads(LB_STATE_FILE.read_text()).get('wallets', {}) if LB_STATE_FILE.exists() else {}
        alerts = []
        for addr, info in lb.items():
            if addr not in prev_raw:
                badge = WATCH_LABEL if addr == WATCH_WALLET else '\U0001f525 NEW LEADERBOARD ENTRY'
                alerts.append(badge + '\nRank #' + str(info['rank']) + ' | ' + (info['name'] or addr[:10]) + '\nVol: $' + str(int(info['vol'])))
        for addr, pinfo in prev_raw.items():
            if addr not in lb:
                alerts.append('\U0001f6ab DROPPED: #' + str(pinfo['rank']) + ' | ' + (pinfo.get('name') or addr[:10]))
        if alerts:
            text = '\U0001f4cb LEADERBOARD UPDATE\n\n' + '\n\n'.join(alerts[:5])
            send(CHANNELS['hub'], text)
            for addr, info in lb.items():
                if addr in prev_raw:
                    prev_rank = prev_raw.get(addr, {}).get('rank', '?')
                    new_rank = info['rank']
                    if str(prev_rank) != str(new_rank):
                        ingest_rank_change(addr, prev_rank, new_rank, info)
        LB_STATE_FILE.write_text(json.dumps({'wallets': lb}, indent=2))
    except Exception as e:
        log.warning('LB change check failed: ' + str(e))


def run():
    global _cycle_sends, _cycle_rl_errors
    _cycle_sends = 0    # reset per-cycle send counter
    _cycle_rl_errors = 0
    state = load_state()
    seen  = set(state.get('seen_keys', []))
    log.info('=== Polyshark Router Run ===')

    _check_leaderboard_changes()
    config.BIG_WIN_MIN_PROFIT_USDC     = MIN_PROFIT
    config.BIG_WIN_MIN_ROI_PCT         = MIN_ROI
    config.BIG_WIN_MIN_TRADE_SIZE_USDC  = MIN_SIZE

    # Check delay queues first
    process_queue(state)

    # Poll for new wins
    try:
        bws = bwd.scan_big_wins_from_leaderboard(top_n=POLL_TOP_N)
        log.info(f'Polled {len(bws)} total big wins')
    except Exception as e:
        log.error(f'Poll error: {e}')
        return

    new_bws = [bw for bw in bws if f'{bw.market_id}_{bw.wallet}' not in seen]
    new_bws.sort(key=lambda bw: bw.timestamp or 0, reverse=True)
    new_bws = new_bws[:MAX_PER_RUN]
    log.info(f'New this run: {len(new_bws)}')
    if not new_bws:
        save_state(state)
        return

    queue = load_queue()

    for bw in new_bws:
        key   = f'{bw.market_id}_{bw.wallet}'
        cats, best_cat = detect_categories_with_confidence(bw.market_question)

        # Ingest alert to OMPA brain
        bw_dict = {
            'market_id': bw.market_id, 'wallet': bw.wallet, 'question': bw.market_question,
            'profit_usdc': bw.profit_usdc, 'roi_pct': bw.roi_pct, 'trade_size_usdc': bw.trade_size_usdc,
            'display_name': bw.display_name, 'timestamp': bw.timestamp, 'outcome': bw.outcome,
            'end_date': bw.end_date, 'avg_price': bw.avg_price,
            'leaderboard_volume': bw.leaderboard_volume if hasattr(bw, 'leaderboard_volume') else 0,
            'win_rate': bw.win_rate if hasattr(bw, 'win_rate') else 0,
            'win_streak': bw.win_streak if hasattr(bw, 'win_streak') else 0,
            'cats': cats
        }
        ingest_alert(bw_dict, cats[0])

        # Queue for sequential forwarding
        is_curated = _is_curated_pick(bw, state)
        queue.append({
            'market_id':     bw.market_id,
            'wallet':        bw.wallet,
            'question':      bw.market_question[:80],
            'profit_usdc':   bw.profit_usdc,
            'roi_pct':       bw.roi_pct,
            'trade_size_usdc': bw.trade_size_usdc,
            'display_name':  bw.display_name or '',
            'timestamp':            bw.timestamp,
            'outcome':              bw.outcome if hasattr(bw, 'outcome') else '',
            'end_date':             bw.end_date if hasattr(bw, 'end_date') else '',
            'avg_price':            bw.avg_price if hasattr(bw, 'avg_price') else 0,
            'leaderboard_volume':   getattr(bw, 'leaderboard_volume', 0),
            'win_rate':             getattr(bw, 'win_rate', 0),
            'win_streak':           getattr(bw, 'win_streak', 0),
            'cats':          cats,
            'best_cat':      best_cat,  # single highest-confidence category
            'cat_sent':      None,
            'pro_sent':       False,
            'free_sent':     False,
            'queued_at':     datetime.now(timezone.utc).isoformat(),
            'is_curated':    is_curated,
            'is_full_pro':    True
        })
        if is_curated:
            state['curated_sent'] = state.get('curated_sent', 0) + 1
            log.info(f'★ CURATED PICK: {bw.market_question[:50]} | ROI {bw.roi_pct:.0f}% | Profit ${bw.profit_usdc:,.0f}')

        seen.add(key)
        state['total_sent'] += 1
        log.info(f'Queued: {bw.market_question[:50]} -> cats={cats} | free in {FREE_DELAY}')

    save_queue(queue)
    state['seen_keys'] = list(seen)[-1000:]
    state['last_run'] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    log.info(f'Done. Total sent: {state["total_sent"]}')

if __name__ == '__main__':
    import time as _time
    log.info('Starting Polyshark Router daemon loop')
    while True:
        if Path('/tmp/polyshark_router_paused').exists():
            log.warning('Router PAUSED — sleeping 60s before rechecking')
            _time.sleep(60)
            continue
        run()
        _time.sleep(120)  # 2 min between cycles
