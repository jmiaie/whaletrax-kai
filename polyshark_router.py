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

ROOT = '/home/ubuntu/.openclaw/workspace'
REPO = '/home/ubuntu/.openclaw/workspace/repos/whaletrax'
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if REPO not in sys.path:
    sys.path.insert(0, REPO)
os.chdir(REPO)
import requests
from src import config, big_win_detector as bwd, polymarket_client as pm
from polyshark_memory import ingest_alert, ingest_fault, ingest_whale, ingest_streak, ingest_rank_change, ingest_market
from wallet_profiles import get_profile
from src.market_enricher import validate_and_enrich

STATE_FILE  = Path('/tmp/polyshark_router_state.json')
QUEUE_FILE  = Path('/tmp/polyshark_router_queue.json')
HEALTH_FILE = Path('/tmp/polyshark_router_health.json')
LOG_FILE    = Path('/tmp/polyshark_router.log')
PAUSE_FILE  = Path('/tmp/polyshark_router_paused')  # anti-spam killswitch
MAX_PER_RUN = 1
MAX_SENDS_PER_CYCLE = 12   # hard cap on total sends per cycle (PRO + category + free)
POLL_TOP_N  = 20
# ── FREE CHANNEL DELAY CONTROLS ─────────────────────────────────────────────────
# FREE_ALERT_DELAY_SECONDS: seconds before free channel fires after item is queued.
# Set to 21600 (6 hrs) for standard free tier delay. Can override via env var.
FREE_ALERT_DELAY_SECONDS = int(os.environ.get('POLYSHARK_FREE_DELAY_SECONDS', '21600'))
FREE_DELAY = timedelta(seconds=FREE_ALERT_DELAY_SECONDS)
# NOTE: Previously hardcoded at 90 minutes (5400s); now defaults to 6 hours.
CURATED_DELAY = timedelta(minutes=5)  # curated forward delay
MAX_CURATED  = 4
CAT_DELAY    = timedelta(minutes=10)
PRO_ALERT_DELAY_SECONDS = int(os.environ.get('POLYSHARK_PRO_DELAY_SECONDS', '0'))  # 0 = fire immediately
PRO_DELAY    = timedelta(seconds=PRO_ALERT_DELAY_SECONDS)
SEND_PAUSE   = 45
MIN_PROFIT   = 500
MIN_ROI      = 50
MIN_SIZE     = 100
MIN_POS_30D  = 3   # Minimum 30d positions required to show the 30Day WR line (else show "—")
SHOW_CONFIDENCE = False   # Toggle: True = show [Confidence: X%] on cards, False = hide
SHOW_NEW_TRADE = True   # Toggle: True = show "🆕 New Trade Opened Today" badge for positions < 24h old

# Per-cycle send tracking (resets each run)
_cycle_sends = 0
_cycle_rl_errors = 0

# Active bot: Kaizen8_bot (8534952394)
# Load bot token from secrets file — never hardcode
_TELEGRAM_TOKEN_FILE = '/home/ubuntu/.openclaw/.secrets/polyshark.env'
def _load_token():
    p = Path(_TELEGRAM_TOKEN_FILE)
    if p.exists():
        for line in p.read_text().splitlines():
            if line.startswith('TELEGRAM_BOT_TOKEN='):
                return line.split('=', 1)[1].strip()
    # Fallback: try gateway config
    import json, re, os
    gw_path = os.path.expanduser('~/.openclaw/openclaw.json')
    if os.path.exists(gw_path):
        raw = open(gw_path).read()
        m = re.search(r'"botToken"\s*:\s*"([^"]+)"', raw)
        if m:
            return m.group(1)
    raise RuntimeError('Telegram bot token not found in secrets or config')
TOKEN = _load_token()

CHANNELS = {
    'alert':    int(os.environ.get('CHANNEL_ALERT_GROUP',         '-1003786930778')),  # Alert Group (internal/bots/personal circle)
    'pro':      int(os.environ.get('CHANNEL_POLYSHARK_PRO',      '-1003739747776')),  # PolysharkPRO
    'top_plays':int(os.environ.get('CHANNEL_TOP_PLAYS_US',      '-1003957370508')),  # Polyshark TOP PLAYS US
    'sports':   int(os.environ.get('CHANNEL_POLYSHARK_SPORTS',  '-1003948034686')),
    'crypto':   int(os.environ.get('CHANNEL_POLYSHARK_CRYPTO',   '-1003999731708')),
    'weather':  int(os.environ.get('CHANNEL_POLYSHARK_WEATHER',  '-1003532326443')),
    'world':    int(os.environ.get('CHANNEL_POLYSHARK_WORLD',    '-1003927756388')),
    'politics': int(os.environ.get('CHANNEL_POLYSHARK_POLITICS', '-1003935178097')),
    'econ':     int(os.environ.get('CHANNEL_POLYSHARK_ECON',     '-1003868008293')),
    'esports':  int(os.environ.get('CHANNEL_POLYSHARK_ESPORTS',  '-1003700788085')),
    'free':     int(os.environ.get('CHANNEL_POLYSHARK_FREE',     '-1003999194095')),  # Polyshark free teaser
    'free_chat': int(os.environ.get('CHANNEL_POLYSHARK_FREE_CHAT','-1003860830659')),
}
CHANNEL_NAMES = {v: k for k, v in CHANNELS.items()}

# US geo-restricted channels — Polymarket URLs won't work for these users
US_GEO_RESTRICTED = {
    -1003786930778,  # Alert Hub (Jeff's main)
    -1003999194095,  # Free
}

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
    'counter-strike','esports','cs2','csgo','valorant','league of legends','lol:','lck','lol worlds',
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
ELECTIONS_KW = ['election','vote','ballot','electoral','electoral college','polling','poll','exit poll',
                'election day','midterm','governor race','senate race','house race','primary','runoff']
IRAN_KW      = ['iran','tehran','persian','iranian','iran nuclear','sanctions',' IAEA']
FINANCE_KW   = ['stock','nasdaq','dow','s&p','earnings','revenue','profit','quarter','sec','sec filing',
                'IPO','market cap','bonds','treasury','yield','debt','credit','loan','bank','banking']
GEOPOLITICS_KW = ['nato','ukraine','russia','china','taiwan','south china sea','sanctions','treaty',
                  'diplomacy','embassy','consulate','UN','UN security council','NATO','WWIII']
TECH_KW      = ['AI','artificial intelligence','meta','google','apple','amazon','nvidia','openai',
                'anthropic','startup','tech','software','chip','semiconductor','LLM','model']
CULTURE_KW   = ['oscar','grammy','emmy','award','movie','film','music','album','song','book',
                'bestseller','festival','concert','exhibit','museum','art','celebrity','star']

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
            q = json.loads(QUEUE_FILE.read_text())
            seen = set()
            deduped = []
            for item in q:
                # Skip items already sent on all channels — they're stale
                if item.get('pro_sent') and item.get('free_sent'):
                    continue
                # Drop items older than 24h regardless
                try:
                    qtime = datetime.fromisoformat(item.get('queued_at','').replace('Z','+00:00')).replace(tzinfo=timezone.utc)
                    if (datetime.now(timezone.utc) - qtime).total_seconds() > 86400:
                        continue
                except Exception:
                    pass
                key = f"{item.get('market_id','')}_{item.get('wallet','')}"
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(item)
            return deduped
        except Exception:
            pass
    return []

def save_queue(q):
    deduped = []
    seen = set()
    for item in q:
        key = f"{item.get('market_id','')}_{item.get('wallet','')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    QUEUE_FILE.write_text(json.dumps(deduped, indent=2))


def set_health(status='ok', detail='', retry_after=0):
    HEALTH_FILE.write_text(json.dumps({
        'status': status,
        'detail': detail,
        'retry_after': retry_after,
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }, indent=2))

def send(cid, text, pause=True):
    """Send Telegram message. Killswitch + rate-limit + per-cycle hard cap."""
    global _cycle_sends, _cycle_rl_errors
    if not text:
        log.warning(f'Send skipped: empty text for {cid}')
        return False
    if PAUSE_FILE.exists():
        log.warning('Router PAUSED — killswitch active (touch /tmp/polyshark_router_paused to resume)')
        return False
    if _cycle_sends >= MAX_SENDS_PER_CYCLE:
        log.warning(f'Hard cap reached ({MAX_SENDS_PER_CYCLE} sends/cycle) — skipping this send')
        return False
    if pause and hasattr(send, '_last_send') and send._last_send:
        elapsed = time.time() - send._last_send
        if elapsed < 0.05:
            time.sleep(0.05 - elapsed)
    try:
        r = requests.post(f'https://api.telegram.org/bot{TOKEN}/sendMessage',
            json={'chat_id': cid, 'text': text, 'parse_mode': 'HTML',
                  'disable_web_page_preview': True}, timeout=20)
        send._last_send = time.time()
        payload = r.json()
        ok = payload.get('ok', False)
        if not ok:
            err = payload.get('description', 'unknown')
            if 'Too Many Requests' in err:
                _cycle_rl_errors += 1
                retry_after = int(payload.get('parameters', {}).get('retry_after', 10) or 10)
                set_health('rate_limited', err, retry_after)
                log.warning(f'Rate limit hit (cycle #{_cycle_rl_errors}): {err} | sleeping {retry_after + 1}s')
                time.sleep(retry_after + 1)
            else:
                log.warning(f'Send failed {cid}: {err}')
                ingest_fault('send_fail', err, {'chat_id': str(cid)})
        if ok:
            _cycle_sends += 1
            set_health('ok', 'sent')
        return ok
    except Exception as e:
        log.error(f'Send error {cid}: {e}')
        ingest_fault('send_exception', str(e), {'chat_id': str(cid)})
        return False

send._last_send = 0.0

def detect_categories_with_confidence(question: str):
    """
    Return (cats, best_cat, best_score) where cats=all matched categories,
    best_cat=single highest-confidence category, best_score=keyword match count.
    Uses SPORTS_ANCHOR_KWS to prevent false positives on team names in non-sports contexts.
    """
    q = question.lower()
    scores = {}
    for cat, kws in [
        ('sports',      SPORTS_KW),
        ('esports',     ESPORTS_KW),
        ('crypto',      CRYPTO_KW),
        ('weather',     WEATHER_KW),
        ('politics',    POLITICS_KW),
        ('world',       WORLD_KW),
        ('econ',        ECON_KW),
        ('elections',   ELECTIONS_KW),
        ('iran',        IRAN_KW),
        ('finance',     FINANCE_KW),
        ('geopolitics', GEOPOLITICS_KW),
        ('tech',        TECH_KW),
        ('culture',     CULTURE_KW),
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
        return (['pro'], 'pro', 0)
    # Minimum confidence threshold: if best score <= 2, skip category (send PRO-only)
    best_score = max(scores.values())
    if best_score <= 2:
        return (['pro'], 'pro', best_score)  # return actual score, not 0
    best_cat = max(scores, key=scores.get)
    return (list(scores.keys()), best_cat, best_score)

def fmt_conf(score):
    """Normalize keyword match count to 0-100% using an asymptotic curve.
    Score 0 → 0%, score 3 → 50%, score 9 → 75%, score 20 → 87%, score ∞ → 100%"""
    return f'{min(round(100 * (1 - 1/(1 + score/3))), 100)}%'


def detect_geo_availability(question: str, cats: list[str]) -> str:
    """
    Return 'US_AVAILABLE', 'NON_US_ONLY', or 'UNKNOWN' based on market category
    and keyword signals. Polymarket geo-restricts: crypto, NFTs, stock tickers, DeFi.
    US sports, elections, politics, and world events are generally US-available.
    """
    q = (question or '').lower()
    NON_US_KW = [
        'bitcoin','btc','ethereum','eth','crypto','solana','dogecoin','coin',
        'nft','defi','web3','token','blockchain','layer 2','staking',
        'binance','coinbase','kraken','uniswap','DEX','yield farm',
        '$aapl','$tsla','$nvda','$amzn','stock ticker','equity',
        'spot etf','bitcoin etf','ethereum etf',
    ]
    US_KW = [
        'election','president','trump','biden','senate','congress','republican',
        'democrat','governor','ballot','vote','electoral',
        'nba','nfl','nhl','mlb','ncaa','ufc','soccer','tennis','golf',
        'super bowl','world series','playoffs','championship',
    ]
    if any(kw in q for kw in NON_US_KW):
        return 'NON_US_ONLY'
    if any(kw in q for kw in US_KW):
        return 'GLOBAL'
    if 'crypto' in cats:
        return 'NON_US_ONLY'
    if 'econ' in cats or any(k in q for k in [
        'inflation','interest rate','fed','recession','stock market','unemployment rate',
    ]):
        return 'NON_US_ONLY'
    if 'sports' in cats or 'esports' in cats:
        return 'GLOBAL'
    if any(k in q for k in ['election','vote','polling','electoral','ballot']):
        return 'GLOBAL'
    return 'UNKNOWN'


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

def format_card(bw, tier='PRO', channel_id=None, free_card=False):
    import datetime as dt
    from wallet_profiles import get_profile

    wallet = (getattr(bw, 'wallet', '') or '').lower()
    prof = get_profile(wallet, min_fresh=False) if wallet else None

    # Wallet age for new-wallet / reactivated note
    # new_wallet = first position (oldest hist) within 30 days (wallet just started trading)
    # reactivated = has positions >30d old AND last trade within 7 days (came back from dormancy)
    wallet_age_days = None
    last_trade_days_ago = None
    try:
        if prof and prof._pos_history:
            hist_sorted = sorted(prof._pos_history, key=lambda p: p.get('ts', 0))
            oldest_ts = hist_sorted[0].get('ts', 0)
            newest_ts = hist_sorted[-1].get('ts', 0)
            if oldest_ts:
                from datetime import datetime, timezone
                wallet_age_days = max(0, int((datetime.now(timezone.utc).timestamp() - oldest_ts) / 86400))
            if newest_ts:
                last_trade_days_ago = max(0, int((datetime.now(timezone.utc).timestamp() - newest_ts) / 86400))
    except Exception:
        wallet_age_days = None
        last_trade_days_ago = None

    entry_px = getattr(bw, 'avg_price', 0) or 0
    if entry_px == 0:
        return None

    trade_size = float(getattr(bw, 'trade_size_usdc', 0) or 0)
    profit_usdc = float(getattr(bw, 'profit_usdc', 0) or 0)
    roi_pct = float(getattr(bw, 'roi_pct', 0) or 0)
    # is_open: use explicit flag from open-position scan, falling back to
    # accepting_orders (CLOB) and then the avg_price heuristic as last resort.
    _explicit_open = getattr(bw, 'is_open', None)
    if _explicit_open is not None:
        is_open = bool(_explicit_open)
    else:
        # Legacy path: closed-position items have no is_open flag
        _clob_accepting = getattr(bw, 'accepting_orders', True)
        is_open = bool(_clob_accepting) if _clob_accepting is not None else (float(entry_px) < 1.0)

    is_resolved = not is_open
    # Use roi_pct and profit_usdc from the scan (computed from cashPnl and curPrice for open,
    # from realized P&L for closed). Do NOT recompute from entry price — that produces
    # wrong values for open positions where the whale's outcome price ≠ market price.
    # Only recompute for closed positions where we have no pre-computed value.
    if is_open:
        pass  # use scan-computed roi_pct and profit_usdc as-is
    else:
        # Closed position: derive from entry vs settlement
        if roi_pct == 0 and entry_px > 0 and entry_px < 1.0:
            roi_pct = (1.0 / entry_px - 1) * 100
        if trade_size > 0:
            profit_usdc = (trade_size / entry_px) - trade_size

    q = getattr(bw, 'market_question', '') or '?'
    # Sport emoji derived from team/player names in the question — mirrors what appears in the market line
    sports_keywords = {
        '⚾': ['yankees','red sox','cubs','dodgers','mets','marlins','astros','phillies','padres','brewers','guardians','tigers','twins','orioles','athletics','rangers','diamondbacks','giants','mariners','reds','rockies',' nationals','dodger','yankee','marlins','royals','whitesox','whites ox'],
        '🏈': ['chiefs','bills','cowboys','packers','patriots','eagles','lions','vikings','saints','buccaneers','raiders','chargers','broncos','falcons','panthers','bears','cardinals','rams','seahawks','giants nyg','jets','bengals','texans','colts','jaguars','browns','steelers','ravens','nfl','football'],
        '🏀': ['celtics','heat','lakers','warriors','clippers','nuggets','suns','mavericks','bucks','hawks','hornets','nets','knicks','magic','pistons','pacers','wizards','cavaliers','bulls','raptors','rockets','spurs','pelicans','jazz','grizzlies','timberwolves','thunder','nba','basketball'],
        '🏒': ['bruins','rangers nyr','maple leafs','canucks','oilers','flames','capitals','stars','predators','hurricanes','devils','islanders','sabres','senators','canadiens','blue jackets','flyers','red wings','sharks','ducks','kings','kraken','golden knights','blues','blackhawks','lightning','wild','nhl','hockey'],
        '⚽': ['fc ','united','city','real madrid','barcelona','arsenal','liverpool','chelsea','manchester','bayern','dortmund','psg','milan','inter','juventus','atletico','tottenham','atalanta','benfica','porto','ajax','leicester','southampton','bournemouth','brighton','brentford','fulham','west ham','villa','palace','forest','Wolves','leeds','charlton','luton','sheffield','norwich','watford','middlesbrough','coventry','blackburn','swansea','hull','bristol','derby','reading','wolves','wolverhampton','nottingham','birmingham city','preston','ipswich','cardiff','sunderland','leicester city','everton','leeds united','manchester united','manchester city','chelsea fc','arsenal fc','tottenham hotspur','liverpool fc'],
        '🎾': ['wta','atp','roland garros','wimbledon','australian open','us open','tennis'],
        '🎮': ['esports','counter-strike','cs2','cs:go','valve','league of legends','lol','riot','epic games','blizzard','tournament','iem','esl','dota','valorant'],
    }
    sport_emoji = ''
    for emoji, kws in sports_keywords.items():
        if any(kw in q.lower() for kw in kws):
            sport_emoji = emoji
            break
    geo_available = getattr(bw, 'geo_available', 'UNKNOWN') or 'UNKNOWN'
    # US flag for US-accessible plays (GLOBAL = sports/tennis/soccer via CLOB)
    # NON_US_ONLY = restricted markets (crypto/finance) → also show 🇺🇸 for US-restricted
    # only true non-accessible geo gets the globe
    if geo_available in ('GLOBAL', 'NON_US_ONLY'):
        geo_tag = '🇺🇸'
        geo_suffix = ' 🇺🇸'
    elif geo_available == 'UNKNOWN':
        geo_tag = ''
        geo_suffix = ''
    else:
        geo_tag = ''
        geo_suffix = ''
    # Jeff's format: 🟢 🦈 [Polyshark PRO{geo_suffix}] 🦈
    # Category tag: show detected category as a colored badge
    cat_tag = ''
    cats_on_bw = getattr(bw, 'cats', []) or []
    if cats_on_bw and 'pro' not in cats_on_bw:
        cat_map = {
            'sports':      '🏈 Sports',
            'esports':     '🎮 Esports',
            'crypto':      '₿ Crypto',
            'weather':     '🌤 Weather',
            'politics':    '🏛 Politics',
            'world':       '🌐 World',
            'econ':        '📊 Economy',
            'elections':   '🗳 Elections',
            'iran':        '🇮🇷 Iran',
            'finance':     '💹 Finance',
            'geopolitics': '🗺 Geopolitics',
            'tech':        '🤖 Tech',
            'culture':     '🎭 Culture',
        }
        # For sports category, skip cat_tag in favor of sport_emoji (already specific sport)
        cat_tags = [cat_map.get(c, f'#{c}') for c in cats_on_bw if c != 'pro' and c not in ('sports',)]
        if cat_tags:
            cat_tag = f"  {cat_tags[0]}"
    # Free card format: simplified header + globe badge (no PRO branding)
    if free_card:
        geo_badge = ' 🌍' if geo_available == 'GLOBAL' else (' 🇺🇸' if geo_available == 'NON_US_ONLY' else '')
        header = f'🟢 🦈 [Polyshark{geo_badge}] 🦈🟢'
        market = f'🎟️ {q}'  # no sport emoji on free cards
    else:
        header = f'🟢 🦈 [Polyshark PRO{geo_suffix}{cat_tag}{sport_emoji}] 🦈🟢'
        market = f'🎟️ {sport_emoji} {q}' if sport_emoji else f'🎟️ {q}'

    # CLOB-enriched fields (set by validate_and_enrich via process_queue)
    yes_price = getattr(bw, 'yes_price', None)
    no_price  = getattr(bw, 'no_price', None)
    yes_outcome = getattr(bw, 'yes_outcome', '') or ''
    no_outcome  = getattr(bw, 'no_outcome', '') or ''
    game_start_fmt = getattr(bw, 'game_start_fmt', '') or ''
    market_slug = getattr(bw, 'market_slug', '') or ''  # already formatted: 'MLB · KC vs CIN · 06/01'
    market_desc = getattr(bw, 'description', '') or ''
    winner = getattr(bw, 'winner', '') or ''

    # BET line: show trader's pick + current CLOB price context
    side_raw = str(getattr(bw, 'outcome', '') or '').upper()
    side = 'YES' if side_raw not in ('DOWN','NO') else 'NO'
    team = (
        getattr(bw, 'outcome', '') or
        getattr(bw, 'team_name', '') or
        getattr(bw, 'team', '') or
        getattr(bw, 'team_city', '') or
        getattr(bw, 'team_location', '') or
        getattr(bw, 'selection_name', '') or
        getattr(bw, 'outcome_name', '') or
        getattr(bw, 'selected_outcome', '') or
        getattr(bw, 'picked_outcome', '') or
        ''
    )
    if team.strip().lower() in ('yes', 'no'):
        bet = '🎯 ⬆️ BET YES' if side == 'YES' else '🎯 ⬇️ BET NO'
    elif team:
        bet = f'🎯 ⬆️ BET {side} on {team}' if side == 'YES' else f'🎯 ⬇️ BET {side} on {team}'
    else:
        bet = f'🎯 ⬆️ BET {side}' if side == 'YES' else f'🎯 ⬇️ BET {side}'

    # Add current market price context to bet line for open trades
    # For open positions: show the whale's current outcome price as "Now:"
    # YES bet → show YES price. NO bet → show NO price.
    # Never show the opposite outcome's price (which was the previous bug).
    side_raw = str(getattr(bw, 'outcome', '') or '').upper()
    side = 'YES' if side_raw not in ('DOWN', 'NO') else 'NO'
    if is_open:
        if side == 'YES':
            now_price = getattr(bw, 'yes_price', 0) or getattr(bw, 'current_price', 0)
        else:
            now_price = getattr(bw, 'no_price', 0) or getattr(bw, 'current_price', 0)
        if now_price > 0:
            entry_pct = entry_px * 100
            cur_pct = now_price * 100
            bet += f' | Now: {cur_pct:.1f}¢'

    size_line = f'💵 ${trade_size:,.0f} position | Entry: {entry_px*100:.1f}¢'
    roi_label = 'potential ROI' if is_open else 'ROI'
    profit = f'💰 +${profit_usdc:,.0f} (+{roi_pct:.2f}% {roi_label})' if profit_usdc >= 0 else f'💰 -${abs(profit_usdc):,.0f} (-{abs(roi_pct):.2f}% {roi_label})'

    # Add market context line (game start, market type)
    context_parts = []
    if game_start_fmt:
        context_parts.append(f'🏟️ {game_start_fmt}')
    if market_slug:
        # Format slug: "mlb-kc-cin-2026-06-01" → "MLB · KC vs Cin · Jun 1"
        slug_clean = market_slug.replace('-', ' ').replace('  ', ' ')
        # 📋 slug line removed — redundant with 🏟️ game start time
    market_context = ' · '.join(context_parts) if context_parts else ''

    # Use profile values for recent/lifetime stats; never derive from ROI or profit line.
    wr_lt = float(getattr(bw, 'win_rate', None) or (prof.win_rate if prof else 0) or 0)
    wr_30 = float(getattr(bw, 'win_rate_30d', None) or (prof.win_rate_30d if prof else 0) or 0)
    pnl_lt = float(getattr(bw, 'total_pnl', None) or (prof.total_pnl if prof else 0) or 0)
    pnl_30 = float(getattr(bw, 'pnl_30d', None) or (prof.pnl_30d if prof else 0) or 0)
    trades_n = int(getattr(bw, 'total_positions', None) or (prof.total_positions if prof else 0) or 0)

    def fmt_wr(v, wins=0, total=0):
        if total > 0:
            # Derive % directly from wins/total to avoid mismatch with pre-calculated v
            pct = f'{int(round(wins/total*100))}%'
            return f'{pct} WR ({wins}/{total})'  # WR after % but before parens
        pct = f'{int(round(v))}%' if v is not None and v >= 0 else '--'
        return pct
    def fmt_pnl(v):
        if v is None:
            return '-$'
        return f'+${v:,.0f}' if v >= 0 else f'-${abs(v):,.0f}'

    # wins_lt: use bw.wins_lt only if it's a meaningful value (not 0 from unset fallback)
    _bw_wins_lt = getattr(bw, 'wins_lt', None)
    wins_lt = int(_bw_wins_lt) if (_bw_wins_lt is not None and _bw_wins_lt > 0) else int(prof.total_wins if prof else 0)
    # wins_30d: use bw.wins_30d only if it's a meaningful value (not 0 from unset fallback)
    _bw_wins_30 = getattr(bw, 'wins_30d', None)
    wins_30 = int(_bw_wins_30) if (_bw_wins_30 is not None and _bw_wins_30 > 0) else int(getattr(prof, '_wins_30d', 0) if prof else 0)
    # pos_lt: use bw.pos_lt only if it's a meaningful value (not 0 from unset fallback)
    _bw_pos_lt = getattr(bw, 'pos_lt', None)
    pos_lt = int(_bw_pos_lt) if (_bw_pos_lt is not None and _bw_pos_lt > 0) else trades_n
    # pos_30d: use bw.pos_30d only if it's a meaningful value (not 0 from unset fallback)
    _bw_pos_30 = getattr(bw, 'pos_30d', None)
    pos_30 = int(_bw_pos_30) if (_bw_pos_30 is not None and _bw_pos_30 > 0) else int(getattr(prof, '_positions_30d', 0) if prof else 0)
    # pos_30d: use bw.pos_30d only if it's a meaningful value (not 0 from unset fallback)
    _bw_pos_30 = getattr(bw, 'pos_30d', None)
    pos_30 = int(_bw_pos_30) if (_bw_pos_30 is not None and _bw_pos_30 > 0) else int(getattr(prof, '_positions_30d', 0) if prof else 0)

    # Jeff's rule: new wallets (≤30 days old) have identical 30D and lifetime stats.
    # Consolidate to one clean line instead of showing redundant "30Day" + "Lifetime".
    is_new_wallet = wallet_age_days is not None and wallet_age_days <= 30
    is_same_stats = (wr_30 == wr_lt and pnl_30 == pnl_lt and pos_30 == pos_lt)
    inverse_candidate = bool(getattr(bw, 'inverse_candidate', False))

    if inverse_candidate:
        inverse_reason = str(getattr(bw, 'inverse_reason', '') or '')
        recent_line = f'🔁 Inverse watch: {fmt_wr(wr_30, wins=wins_30, total=pos_30) if pos_30 >= MIN_POS_30D else "—"} | — P/L'
        lifetime_line = f'⚠️ Fade candidate: {fmt_wr(wr_lt, wins=wins_lt, total=pos_lt)} | — P/L'
        combined_line = None
        inverse_reason = str(getattr(bw, 'inverse_reason', '') or '')
        recent_line = f'🔁 Inverse watch: {fmt_wr(wr_30, wins=wins_30, total=pos_30) if pos_30 >= MIN_POS_30D else "—"} | — P/L'
        lifetime_line = f'⚠️ Fade candidate: {fmt_wr(wr_lt, wins=wins_lt, total=pos_lt)} | — P/L'
        combined_line = None
    elif is_new_wallet and is_same_stats:
        # Same stats — show one clean line, skip both 30Day and Lifetime
        combined_pct = int(round(wr_lt)) if wr_lt is not None and wr_lt >= 0 else 0
        combined_wins = wins_lt
        combined_total = pos_lt
        if combined_total > 0:
            pct_str = f'{int(round(combined_wins/combined_total*100))}%'
        else:
            pct_str = f'{int(round(wr_lt))}%' if wr_lt is not None and wr_lt >= 0 else '--'
        combined_line = f'🏅 {pct_str} WR ({combined_wins}/{combined_total}) | 💰 {fmt_pnl(pnl_lt)} P/L'
        recent_line = None
        lifetime_line = None
    else:
        # Normal case — show both 30Day and Lifetime as separate lines
        combined_line = None
        if pos_30 >= MIN_POS_30D:
            recent_line = f'🏅 30Day: {fmt_wr(wr_30, wins=wins_30, total=pos_30)} | 💰 {fmt_pnl(pnl_30)} P/L'
        else:
            recent_line = f'🏅 30Day: — WR | — P/L'
        lifetime_line = f'🏆 Lifetime: {fmt_wr(wr_lt, wins=wins_lt, total=pos_lt)} | 💵 {fmt_pnl(pnl_lt)} P/L'
    has_old_history = (wallet_age_days is not None and wallet_age_days > 30)
    is_reactivated = has_old_history and (last_trade_days_ago is not None and last_trade_days_ago <= 7)
    # Badge conditions (track separately for lifetime suppression logic)
    badge_pos_lt10 = wallet_age_days is not None and wallet_age_days <= 30 and pos_lt < 10
    if wallet_age_days is not None and wallet_age_days <= 30:
        new_wallet_line = '🆕 New wallet: less than a month of experience'
    elif is_reactivated:
        new_wallet_line = '🔄 Reactivated wallet: returned from dormancy'
    else:
        new_wallet_line = ''
    # Only suppress lifetime line for wallets that are BOTH young AND have limited history
    suppress_lifetime = badge_pos_lt10
    conf = f'[Confidence: {fmt_conf(getattr(bw, "confidence", 0))}]'

    abbrev = f'{wallet[:6]}...{wallet[-5:]}' if wallet else '0x—'
    trader_link = f'[{abbrev}](https://polymarket.com/profile/{wallet})' if wallet else '0x—'
    # Geo badge after 🐋 — use CLOB-enriched geo or fallback to queue-item geo
    geo = getattr(bw, 'geo_available', '') or 'UNKNOWN'
    if geo == 'GLOBAL' or geo == 'NON_US_ONLY':
        geo_badge = ' 🇺🇸'
    elif geo == 'UNKNOWN':
        geo_badge = ''
    else:
        geo_badge = ''
    trader = f'🌊 <a href="https://polymarket.com/profile/{wallet}">{abbrev}</a> 🐋{geo_badge}'

    end_date = getattr(bw, 'end_date', '') or ''
    trade_ts = int(getattr(bw, 'timestamp', 0) or 0)
    trade_date = dt.datetime.fromtimestamp(trade_ts, tz=dt.timezone.utc).strftime('%Y-%m-%d') if trade_ts else '—'
    # Format: O: 06-02 | C: 2026-06-02 | 🏟️ game start time
    # Format: O: 06-02 | C: 06-02-2026
    open_short = trade_date[5:10] if trade_date and len(trade_date) >= 10 else trade_date  # MM-DD
    close_fmt = end_date[:10]  # YYYY-MM-DD if end_date and len(end_date) >= 10 else '—'
    if game_start_fmt:
        dates_line = f'📅 O: {open_short} | C: {close_fmt} | 🏟️ {game_start_fmt}'
    else:
        dates_line = f'📅 O: {open_short} | C: {close_fmt}'

    # Re-check CLOB at format time: if market is no longer accepting orders, it's RESOLVED
    is_resolved = not getattr(bw, 'accepting_orders', True)  # True = open by default
    if is_resolved:
        trade_open_line = '✅ RESOLVED — position closed'
        # For resolved markets: use wallet profile's total_pnl as reference P&L
        # The profit_usdc from leaderboard = potential, not actual realized
        pnl_label = ''  # Wallet line removed — redundant with Lifetime P/L
    else:
        # New Trade badge: flag if position was opened within the last 24 hours
        trade_open_line = ''
        pnl_label = ''
        if trade_ts > 0:
            age_hours = (dt.datetime.now(dt.timezone.utc).timestamp() - trade_ts) / 3600
            if age_hours <= 24:
                trade_open_line = '🆕 New Trade Opened Today'

    geo_available = getattr(bw, 'geo_available', 'UNKNOWN') or 'UNKNOWN'
    if geo_available == 'GLOBAL':
        geo_tag = '🌍 Global'
    elif geo_available == 'NON_US_ONLY':
        geo_tag = '🇺🇸 US Only'
    else:
        geo_tag = ''
    lines = [header]
    if SHOW_NEW_TRADE and trade_open_line:
        lines.append(trade_open_line)
    if inverse_candidate and inverse_reason:
        lines.append(f'🧭 Inverse candidate: {inverse_reason}')
    if new_wallet_line:
        lines.append(new_wallet_line)
    lines += [
        '————————————————————————',
        market,
    ]
    lines += [
        '————————————————————————',
        profit,
        size_line,
        '',
        bet,
        dates_line,
    ]
    # market_context (game start) is now merged into dates_line above
    # if market_context:
    if pnl_label:
        lines.append(pnl_label)
    if combined_line:
        lines.append(combined_line)
    elif recent_line:
        lines.append(recent_line)
        if lifetime_line:
            lines.append(lifetime_line)
    if SHOW_CONFIDENCE:
        lines.append(conf)
    lines += [
        '————————————————————————',
        trader,
    ]
    # Event link last = Telegram link preview shows the play/market, not the wallet
    market_id = getattr(bw, 'market_id', '') or ''
    if market_id:
        lines.append(f'🔗 https://polymarket.com/event/{market_id}')
    # geo tag is now in the header — no need to repeat at footer
    return '\n'.join(lines)
def process_queue(state):
    """Fire category forwards (7 min) and free forwards (6 hr)."""
    queue = load_queue()
    if not queue:
        return
    now = datetime.now(timezone.utc)
    updated = []
    dirty = False
    for item in queue:
        queued_at = datetime.fromisoformat(item['queued_at']).replace(tzinfo=timezone.utc)
        cat_ready  = (now - queued_at) >= CAT_DELAY
        free_ready = (now - queued_at) >= FREE_DELAY
        pro_ready  = (now - queued_at) >= PRO_DELAY

        # Pro channel — fire once when ready (3-min delay)
        if pro_ready and not item.get('pro_sent'):
            item_hash = f"{item.get('market_id','')}_{item.get('wallet','')}"
            if item.get('_fired_hash') == item_hash:
                log.warning(f'DUPLICATE PRO FIRE BLOCKED: {item["question"][:40]}')
                item['pro_sent'] = True
                dirty = True
                continue
            bw = bw_from_item(item)
            if bw is None:
                log.info(f'PRO filtered (resolved/null): {item["question"][:40]}')
                item['pro_sent'] = True
                dirty = True
                continue

            # Drop resolved items: check is_open flag and endDate
            # A resolved market has: redeemable=true, percentPnl=-100, or endDate in the past
            item_is_open = item.get('is_open', True)
            item_end = item.get('end_date', '')
            item_pct_pnl = float(item.get('percentPnl', 0) or 0)
            item_redeemable = item.get('redeemable', False)
            today_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            is_resolved_item = (
                item_is_open is False
                or item_redeemable is True
                or item_pct_pnl <= -99
                or (item_end and item_end < today_str)
            )
            if is_resolved_item:
                log.info(f'PRO filtered (resolved market): {item["question"][:40]}')
                item['pro_sent'] = True
                dirty = True
                continue

            # CLOB validation for queued items (check once per item)
            if not item.get('_clob_validated'):
                try:
                    enriched = validate_and_enrich(bw)
                except Exception as e:
                    log.warning(f'CLOB validation error for queued item: {e}')
                    enriched = bw
                if enriched is None:
                    log.info(f"CLOB rejected queued item: {item.get('market_id','')[:20]}...")
                    item['pro_sent'] = True  # mark sent so it won't reprocess
                    dirty = True
                    continue
                item['_clob_validated'] = True
                # Store enriched data on item so it persists for format_card
                if isinstance(enriched, dict):
                    item['_clob_enriched'] = {k: v for k, v in enriched.items()
                                              if k not in ('market_id',)}
            # Attach CLOB enrichment: prices, game start, geo, etc.
            # First-time validation: enriched dict has everything from CLOB
            # Already-validated items: use stored _clob_enriched
            enriched_data = item.get('_clob_enriched') if item.get('_clob_validated') else (enriched if isinstance(enriched, dict) else None)
            if enriched_data:
                for k, v in enriched_data.items():
                    if k not in ('market_id',):
                        setattr(bw, k, v)
            # Ensure geo_available is set — prefer CLOB-enriched geo over queue-item fallback
            if not getattr(bw, 'geo_available', None):
                bw.geo_available = item.get('geo_available', 'UNKNOWN')
            # Final check before sending: skip fully resolved cards (yes_price = $1.00)
            # NOTE: removed hard block here — the resolved-check below handles this case
            # by routing resolved cards to Alert Hub only (not PRO/TOP PLAYS)

            # Market resolved — skip PRO and TOP PLAYS entirely
            # Send as RESOLVED update only to Alert Hub (bots only)
            try:
                info = pm.get_market(bw.market_id) if hasattr(bw, 'market_id') else None
                if info and not info.get('accepting_orders', True):
                    resolved_card = format_card(bw, 'pro', CHANNELS['alert'])
                    if resolved_card:
                        send(CHANNELS['alert'], resolved_card)
                        # DO NOT send to PRO or TOP PLAYS — resolved plays are curated-only
                    item['_fired_hash'] = item_hash
                    item['pro_sent'] = True
                    dirty = True
                    log.info(f'PRO resolved (alert only, not PRO): {item["question"][:40]}')
                    continue
            except Exception as e:
                log.warning(f'Resolved check error: {e}')

            # Flow: alert (internal/bots) → pro (queue for Jeff to review)
            # Jeff manually forwards best cards from PRO → Polyshark TOP PLAYS US
            card = format_card(bw, 'pro', CHANNELS['alert'])
            if card:
                ok_alert = send(CHANNELS['alert'], card)
                ok_pro   = send(CHANNELS['pro'], card)
                log.info(f'Send result — alert={ok_alert}, pro={ok_pro}: {item["question"][:40]}')

                # Auto-route to TOP PLAYS US: top-tier wallets, entry < 60¢, market OPEN
                # HARD GATE: resolved plays (accepting_orders=False) never go to TOP PLAYS
                try:
                    if getattr(bw, 'accepting_orders', True) is not True:
                        pass  # skip — resolved
                    else:
                        tp_wallet = (getattr(bw, 'wallet', '') or '').lower()
                        tp_prof = get_profile(tp_wallet, min_fresh=False) if tp_wallet else None
                        if is_top_play(bw, tp_prof):
                            tp_card = format_card(bw, 'pro', CHANNELS['top_plays'])
                            if tp_card:
                                ok_top = send(CHANNELS['top_plays'], tp_card)
                                log.info(f'TOP PLAYS auto-routed: {item["question"][:40]}')
                except Exception as e:
                    log.warning(f'TOP PLAYS routing error: {e}')

                # World channel: standalone high-WR probability filter
                # Fires immediately (same time as PRO) for any wallet with WR >= 90% (lifetime OR 30D)
                # Not gated by category — any qualifying wallet's card routes here
                try:
                    if not item.get('world_sent'):
                        w_wallet = (getattr(bw, 'wallet', '') or '').lower()
                        w_prof = get_profile(w_wallet, min_fresh=False) if w_wallet else None
                        wr_lt = w_prof.win_rate  if w_prof else 0
                        wr_30 = w_prof.win_rate_30d if w_prof else 0
                        if wr_lt >= 90 or wr_30 >= 90:
                            w_card = format_card(bw, 'pro', CHANNELS['world'])
                            if w_card:
                                ok_world = send(CHANNELS['world'], w_card)
                                if ok_world:
                                    item['world_sent'] = True
                                    log.info(f'World channel fired (WR {wr_lt:.0f}%/{wr_30:.0f}%): {item["question"][:40]}')
                                else:
                                    item['world_sent'] = True
                except Exception as e:
                    log.warning(f'World routing error: {e}')

                if ok_alert or ok_pro:
                    try:
                        from card_stats import ingest_card
                        ingest_card(bw, tier='pro', channel='alert')
                    except Exception as e:
                        log.warning(f'card_stats ingest error: {e}')
                item['_fired_hash'] = item_hash
                log.info(f'PRO delay fired: {item["question"][:40]}')
                item['pro_sent'] = True
                dirty = True
            else:
                log.info(f'PRO filtered (null card): {item["question"][:40]}')
                item['pro_sent'] = True
                dirty = True

        # Category routing: send to Sports (and other category channels) with 10-min delay
        if cat_ready and item.get('cat_sent') != item['cats']:
            bw_cat = bw_from_item(item)
            if bw_cat:
                cats = item.get('cats', [])
                for cat in cats:
                    if cat == 'pro':
                        continue
                    channel_map = {
                        'sports': CHANNELS.get('sports'),
                        'esports': CHANNELS.get('sports'),  # esports → Sports (no separate esports channel)
                        'crypto': CHANNELS.get('crypto'),
                        'weather': CHANNELS.get('weather'),
                        'politics': CHANNELS.get('politics'),
                        'world': CHANNELS.get('world'),
                        'econ': CHANNELS.get('econ'),
                    }
                    cat_channel = channel_map.get(cat)
                    if cat_channel:
                        try:
                            # World channel filter: only send if EITHER lifetime WR >= 90% OR 30D WR >= 90%
                            if cat == 'world':
                                prof_w = get_profile(bw_cat.wallet, min_fresh=False) if getattr(bw_cat, 'wallet', None) else None
                                wr_lt  = prof_w.win_rate  if prof_w else 0
                                wr_30  = prof_w.win_rate_30d if prof_w else 0
                                if wr_lt < 90 and wr_30 < 90:
                                    log.info(f'World filtered (WR {wr_lt:.0f}%/{wr_30:.0f}% both below 90%): {item["question"][:40]}')
                                    continue
                            cat_card = format_card(bw_cat, 'pro', cat_channel)
                            if cat_card:
                                send(cat_channel, cat_card)
                                log.info(f'Category [{cat}] fired: {item["question"][:40]}')
                        except Exception as e:
                            log.warning(f'Category [{cat}] send error: {e}')
            item['cat_sent'] = item['cats']
            dirty = True
            log.info(f'Category routing done for: {item["question"][:40]}')

        # ⚡ Free channel disabled during v2.0 rollout: Hub + PRO only.
        # ⚠️ Keep queued items for downstream review, but do not emit to free channels.
        curated_ready = (now - queued_at) >= CURATED_DELAY
        free_ready    = (now - queued_at) >= FREE_DELAY
        item_ready    = curated_ready if item.get('is_curated') else free_ready

        if item_ready and not item.get('free_sent'):
            # Format as FREE card (simplified: no PRO branding, globe badge, reduced stats)
            try:
                bw_free = bw_from_item(item) if 'bw_from_item' in dir() else None
                if bw_free:
                    # Enrich with CLOB data before formatting
                    try:
                        bw_enr = validate_and_enrich(bw_free)
                        if bw_enr is None:
                            item['free_sent'] = True
                            dirty = True
                            continue
                        if isinstance(bw_enr, dict):
                            for k, v in bw_enr.items():
                                if k not in ('market_id',):
                                    setattr(bw_free, k, v)
                    except Exception as e:
                        log.warning(f'Free CLOB enrich error: {e}')
                        item['free_sent'] = True
                        dirty = True
                        continue

                    free_card_text = format_card(bw_free, 'free', CHANNELS.get('free'), free_card=True)
                    if free_card_text:
                        send(CHANNELS['free'], free_card_text)
                        log.info(f'FREE fired: {item["question"][:40]}')
            except Exception as e:
                log.warning(f'Free channel error: {e}')
            item['free_sent'] = True
            dirty = True

        updated.append(item)

    if dirty or len(updated) < len(queue):
        save_queue(updated)

def bw_from_item(item):
    """Reconstruct a minimal object from queued item.
    
    CLOB-re-enriches the item if not already validated (for old queue items that
    predate the enrichment step). This ensures accepting_orders, yes_price, etc.
    are populated for TOP PLAYS gating and resolved-card handling.
    """
    # Re-enrich via CLOB if not already done
    if not item.get('_clob_validated'):
        from src.market_enricher import validate_and_enrich
        class _BW:
            pass
        _tmp = _BW()
        _tmp.market_id = item.get('market_id', '')
        try:
            enriched = validate_and_enrich(_tmp)
            if isinstance(enriched, dict):
                item['_clob_enriched'] = {k: v for k, v in enriched.items() if k != 'market_id'}
                item['_clob_validated'] = True
        except Exception:
            pass

    from datetime import datetime, timezone as _tz

    # Build a simple namespace object instead of a class
    import json as _json
    class BW:
        pass

    bw = BW()
    bw.market_question     = item.get('question','')
    bw.market_id           = item.get('market_id','')
    bw.wallet              = item.get('wallet','')
    bw.profit_usdc         = item.get('profit_usdc', 0)
    bw.roi_pct             = item.get('roi_pct', 0)
    bw.trade_size_usdc     = item.get('trade_size_usdc', 0)
    bw.display_name         = item.get('display_name', '')
    bw.timestamp            = item.get('timestamp')
    bw.leaderboard_volume  = item.get('leaderboard_volume', 0)
    bw.outcome             = item.get('outcome','')
    bw.end_date            = item.get('end_date','')
    bw.avg_price           = item.get('avg_price', 0)
    bw.is_open             = item.get('is_open', False)   # True = open position, False = closed
    bw.current_price       = item.get('current_price', 0) # CLOB price at detection time
    bw.unrealized_pnl      = item.get('unrealized_pnl', 0) # mark-to-market P&L for open positions
    bw.percentPnl          = item.get('percentPnl', 0)   # Polymarket position % P&L
    bw.redeemable          = item.get('redeemable', False) # True = market resolved
    # CLOB enriched data — use stored CLOB enrichment if available (from validate_and_enrich)
    # This ensures accepting_orders, yes_price, geo_available are set correctly for TOP PLAYS gating
    clob = item.get('_clob_enriched', {})
    bw.accepting_orders    = clob.get('accepting_orders', item.get('accepting_orders', True))
    bw.yes_price          = clob.get('yes_price', item.get('yes_price', 0))
    bw.no_price           = clob.get('no_price', item.get('no_price', 0))
    bw.geo_available      = clob.get('geo_available', item.get('geo_available', 'UNKNOWN'))
    bw.game_start_time    = clob.get('game_start_time', item.get('game_start_time', ''))
    bw.market_slug       = clob.get('market_slug', item.get('market_slug', ''))
    # Detect and store categories for card tagging
    cats_det, bw.best_cat, bw.conf_score = detect_categories_with_confidence(item.get('question',''))
    bw.cats = cats_det
    bw.is_curated          = item.get('is_curated', False)
    bw.confidence          = item.get('conf_score', 0)  # keyword match count (0 = low/no match)
    bw.win_rate            = getattr(bw, 'win_rate', 0) or 0
    bw.win_rate_30d        = getattr(bw, 'win_rate_30d', 0) or 0
    bw.total_positions      = getattr(bw, 'total_positions', 0) or 0
    bw.win_streak          = getattr(bw, 'win_streak', 0) or 0

    # Look up wallet profile for real win rate / streak / trade count.
    # Profile is the authoritative source — always prefer it over queue-item cache.
    # Only fall back to queue-item values when the wallet has no profile at all (0 positions).
    try:
        prof = get_profile(bw.wallet, min_fresh=False) if bw.wallet else None
        if prof and prof.total_positions > 0:
            bw.win_rate        = prof.win_rate
            bw.win_rate_30d   = prof.win_rate_30d
            bw.total_positions= prof.total_positions
            bw.win_streak     = prof.current_streak
            bw.pnl_30d        = getattr(prof, 'pnl_30d', 0)
            bw.wins_lt        = prof.total_wins
            bw.wins_30d       = getattr(prof, '_wins_30d', 0)
            bw.pos_30d        = getattr(prof, '_positions_30d', 0)  # actual 30d position count
            bw.pos_lt         = prof.total_positions  # lifetime position count
        elif prof and prof.total_positions == 0:
            # Profile exists but has no positions — use queue item as fallback
            bw.win_rate        = bw.win_rate        or item.get('win_rate', 0) or 0
            bw.win_rate_30d    = bw.win_rate_30d    or item.get('win_rate_30d', 0) or 0
            bw.total_positions = bw.total_positions or item.get('total_positions', 0) or 0
            bw.win_streak     = bw.win_streak      or item.get('win_streak', 0) or 0
            bw.wins_lt        = item.get('wins_lt', 0)
            bw.wins_30d       = item.get('wins_30d', 0)
            bw.pos_lt         = item.get('pos_lt', 0)
            bw.pos_30d        = item.get('pos_30d', 0)
        # else: no profile at all — use queue item values directly
        else:
            bw.win_rate        = item.get('win_rate', 0) or 0
            bw.win_rate_30d    = item.get('win_rate_30d', 0) or 0
            bw.total_positions = item.get('total_positions', 0) or 0
            bw.win_streak     = item.get('win_streak', 0) or 0
            bw.wins_lt        = item.get('wins_lt', 0)
            bw.wins_30d       = item.get('wins_30d', 0)
            bw.pos_lt         = item.get('pos_lt', 0)
            bw.pos_30d        = item.get('pos_30d', 0)
    except Exception:
        # On any error, fall back to queue item
        bw.win_rate        = item.get('win_rate', 0) or 0
        bw.win_rate_30d    = item.get('win_rate_30d', 0) or 0
        bw.total_positions = item.get('total_positions', 0) or 0
        bw.win_streak     = item.get('win_streak', 0) or 0
        bw.wins_lt        = item.get('wins_lt', 0)
        bw.wins_30d       = item.get('wins_30d', 0)
        bw.pos_lt         = item.get('pos_lt', 0)
        bw.pos_30d        = item.get('pos_30d', 0)
    return bw


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
            send(CHANNELS['alert'], text)
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

    # ── PRIMARY: Scan OPEN positions (real-time entry detection) ───────────
    # ── STATS:    Update profiles from closed positions (no cards emitted) ───
    try:
        # Primary: open positions as live entry signals
        bws_open = bwd.scan_open_positions(top_n=POLL_TOP_N)
        log.info(f'Open positions scanned: {len(bws_open)}')
    except Exception as e:
        log.error(f'Open-position scan error: {e}')
        bws_open = []

    # Stats-only: closed positions update profiles (no card emission)
    try:
        bwd.scan_big_wins_from_leaderboard(top_n=POLL_TOP_N)
    except Exception as e:
        log.warning(f'Stats scan error: {e}')

    # Filter to truly new (not seen) open positions
    new_bws = [bw for bw in bws_open if f'{bw.market_id}_{bw.wallet}' not in seen]
    new_bws.sort(key=lambda bw: bw.timestamp or 0, reverse=True)
    new_bws = new_bws[:MAX_PER_RUN]
    log.info(f'New this run: {len(new_bws)}')
    if not new_bws:
        save_state(state)
        return

    queue = load_queue()

    # ── CLOB Validation: reject already-resolved markets ─────────────────────
    validated_bws = []
    for bw in new_bws:
        # For open positions: validate market is still accepting orders
        enriched = validate_and_enrich(bw)
        if enriched is None:
            log.info(f'CLOB rejected (resolved/stale): {bw.market_id[:20]}...')
            continue
        validated_bws.append(bw)
    skipped = len(new_bws) - len(validated_bws)
    new_bws = validated_bws
    log.info(f'CLOB validation: {len(new_bws)} passed, {skipped} rejected')
    if not new_bws:
        save_state(state)
        return

    for bw in new_bws:
        key   = f'{bw.market_id}_{bw.wallet}'
        cats, best_cat, conf_score = detect_categories_with_confidence(bw.market_question)
        geo_available = detect_geo_availability(bw.market_question, cats)
        conf = f'[Confidence: {fmt_conf(conf_score)}]'

        # Ingest alert to OMPA brain
        bw_dict = {
            'market_id': bw.market_id, 'wallet': bw.wallet, 'question': bw.market_question,
            'profit_usdc': bw.profit_usdc, 'roi_pct': bw.roi_pct, 'trade_size_usdc': bw.trade_size_usdc,
            'display_name': bw.display_name, 'timestamp': bw.timestamp, 'outcome': bw.outcome,
            'end_date': bw.end_date, 'avg_price': bw.avg_price,
            'leaderboard_volume': bw.leaderboard_volume if hasattr(bw, 'leaderboard_volume') else 0,
            'win_rate': bw.win_rate if hasattr(bw, 'win_rate') else 0,
            'win_streak': bw.win_streak if hasattr(bw, 'win_streak') else 0,
            'cats': cats, 'geo_available': geo_available,
            'is_open': getattr(bw, 'is_open', True),
            'current_price': getattr(bw, 'current_price', 0),
            'unrealized_pnl': getattr(bw, 'unrealized_pnl', 0),
            'percentPnl': getattr(bw, 'percentPnl', 0),
            'redeemable': getattr(bw, 'redeemable', False),
        }
        ingest_alert(bw_dict, cats[0])

        # Enrich with CLOB data before queuing so yes_price/current_price are live
        # This makes the "Now: X.X¢" line in format_card accurate at queue time
        try:
            enriched = validate_and_enrich(bw)
            if enriched and isinstance(enriched, dict):
                bw.yes_price = enriched.get('yes_price', bw.current_price)
                bw.no_price  = enriched.get('no_price', 0)
                bw.accepting_orders = enriched.get('accepting_orders', True)
                bw.game_start_fmt = enriched.get('game_start_fmt', '')
                bw.market_slug = enriched.get('market_slug', '')
                bw.geo_available = enriched.get('geo_available', 'UNKNOWN')
        except Exception as e:
            log.warning(f'CLOB pre-enrich error: {e}')

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
            'win_rate_30d':         getattr(bw, 'win_rate_30d', 0),
            'pnl_30d':              getattr(bw, 'pnl_30d', 0),
            'total_positions':      getattr(bw, 'total_positions', 0),
            'wins_lt':              getattr(bw, 'wins_lt', 0),
            'wins_30d':             getattr(bw, 'wins_30d', 0),
            'pos_lt':              getattr(bw, 'pos_lt', 0),
            'pos_30d':             getattr(bw, 'pos_30d', 0),
            'win_streak':           getattr(bw, 'win_streak', 0),
            'cats':          cats,
            'best_cat':      best_cat,
            'geo_available': geo_available,
            'conf_score':     conf_score,
            'cat_sent':      None,
            'pro_sent':       False,
            'free_sent':     False,
            'world_sent':    False,
            'queued_at':     datetime.now(timezone.utc).isoformat(),
            'is_curated':    is_curated,
            'is_full_pro':    True,
            'is_open':        getattr(bw, 'is_open', True),
            'current_price':  getattr(bw, 'current_price', 0),
            'unrealized_pnl': getattr(bw, 'unrealized_pnl', 0),
            'percentPnl':     getattr(bw, 'percentPnl', 0),
            'redeemable':     getattr(bw, 'redeemable', False),
        })
        if is_curated:
            state['curated_sent'] = state.get('curated_sent', 0) + 1
            log.info(f'★ CURATED PICK: {bw.market_question[:50]} | ROI +{bw.roi_pct:.0f}% | Profit +${bw.profit_usdc:,.0f}')

        seen.add(key)
        state['total_sent'] += 1
        log.info(f'Queued [OPEN]: {bw.market_question[:50]} | size=${bw.trade_size_usdc:,.0f} | entry={bw.avg_price*100:.1f}¢ | cats={cats}')

    save_queue(queue)
    state['seen_keys'] = list(seen)[-1000:]
    state['last_run'] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    log.info(f'Done. Total sent: {state["total_sent"]}')

# ═══════════════════════════════════════════════════════════════════
# TOP PLAYS — AUTOROUTING FILTER
# ═══════════════════════════════════════════════════════════════════
# Criteria for auto-routing to Polyshark TOP PLAYS US:
#   1. Wallet is in the top-tier list (100% WR, 50+ positions, verified P&L)
#   2. Entry price < 50¢ (targets 100%+ potential ROI, not near-guaranteed snipes)
#   3. Market is still open (not resolved)
#   4. Not already sent to TOP_PLAYS this session
#
# Compounding sizing tiers (per position_sizer.py):
#   Balance  $0-$5K   → cap $500/trade
#   Balance  $5K-$20K  → cap $1,000/trade
#   Balance  $20K-$50K → cap $2,500/trade
#   Balance  $50K-$200K → cap $5,000/trade
#   Balance  $200K+    → cap $10,000/trade
#   Daily exposure cap: 25% of balance, split across open positions
# ═══════════════════════════════════════════════════════════════════

TOP_PLAYS_WALLETS = {
    '0x63a51cbb37341837b873bc29d05f482bc2988e33': {'name': 'C1 Whale', 'wr': 85.3, 'positions': 9999, 'pnl': 4_399_805},  # Jeff's #2 Polymarket — high-freq winning whale
    '0x492442eab586f242b53bda933fd5de859c8a3782': {'name': 'Whale A', 'wr': 100.0, 'positions': 200, 'pnl': 49_796_390},
    '0x2a2c53bd278c04da9962fcf96490e17f3dfb9bc1': {'name': 'Whale B', 'wr': 100.0, 'positions': 200, 'pnl': 20_009_550},
    '0x24c8cf69a0e0a17eee21f69d29752bfa32e823e1': {'name': 'Whale C', 'wr': 100.0, 'positions': 50,  'pnl': 17_467_534},
    '0x6a72f61820b26b1fe4d956e17b6dc2a1ea3033ee': {'name': 'Whale D', 'wr': 100.0, 'positions': 50,  'pnl': 16_867_771},
    '0xfe787d2da716d60e8acff57fb87eb13cd4d10319': {'name': 'Whale E', 'wr': 100.0, 'positions': 5000,'pnl': 15_823_457},
}

TOP_PLAYS_WHITELIST = set(TOP_PLAYS_WALLETS.keys())

TOP_PLAYS_CONFIG = {
    'max_entry_price': 0.60,  # <60¢: <50¢ = high priority, 50-60¢ = secondary
    'min_wr': 95.0,               # Wallet must have 95%+ lifetime WR
    'require_30d_activity': True,  # Wallet must have traded in last 30 days
}

def is_top_play(bw, prof=None) -> bool:
    """Return True if this signal qualifies for TOP PLAYS US channel.
    
    Criteria:
    - Wallet has 95%+ lifetime WR AND 20+ lifetime positions
      OR wallet is in the hardcoded TOP_PLAYS_WHITELIST (verified top-tier whales)
    - Entry price < 60¢ (< 50¢ = high priority, 50-60¢ = secondary)
    - Market is OPEN (not resolved — accepting_orders must be True)
    """
    wallet = (getattr(bw, 'wallet', '') or '').lower()
    if not wallet:
        return False
    
    # Check entry price — must be below 60¢
    entry_px = float(getattr(bw, 'avg_price', 0) or 0)
    if entry_px == 0 or entry_px >= TOP_PLAYS_CONFIG['max_entry_price']:
        return False
    
    # Hardcoded top-tier whales (100% WR, verified P&L) — bypass market-open check
    # These whales go to TOP PLAYS regardless of market status since they're verified
    if wallet in TOP_PLAYS_WHITELIST:
        return True
    
    # Dynamic check: wallet must have 95%+ WR and 20+ positions for TOP PLAYS
    # AND market must be open (not resolved)
    if prof:
        wr = getattr(prof, 'win_rate', 0) or 0
        pos = getattr(prof, 'total_positions', 0) or 0
        if wr >= TOP_PLAYS_CONFIG['min_wr'] and pos >= 20:
            # Must be open market — skip resolved/settled positions for dynamic whales
            if getattr(bw, 'accepting_orders', True) is not True:
                return False
            return True
    
    return False

if __name__ == '__main__':
    import time as _time
    log.info('Starting Polyshark Router daemon loop')
    while True:
        if Path('/tmp/polyshark_router_paused').exists():
            log.warning('Router PAUSED — sleeping 60s before rechecking')
            _time.sleep(60)
            continue
        run()
        _time.sleep(120)  # 2 min router poll interval

