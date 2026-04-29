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
from src.market_enricher import validate_and_enrich

STATE_FILE  = Path('/tmp/polyshark_router_state.json')
QUEUE_FILE  = Path('/tmp/polyshark_router_queue.json')
HEALTH_FILE = Path('/tmp/polyshark_router_health.json')
LOG_FILE    = Path('/tmp/polyshark_router.log')
PAUSE_FILE  = Path('/tmp/polyshark_router_paused')  # anti-spam killswitch
MAX_PER_RUN = 1
MAX_SENDS_PER_CYCLE = 12   # hard cap on total sends per cycle (PRO + category + free)
POLL_TOP_N  = 20
FREE_DELAY   = timedelta(minutes=90)
CURATED_DELAY = timedelta(minutes=5)  # curated forward delay
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

TOKEN = '8741871021:AAGtWosFayhX82ls7W3ZNcNh5cIQcEbAEpM'
TOKEN = os.environ.get('POLYSHARK_ADMIN_BOT_TOKEN', os.environ.get('POLYSHARK_BOT_TOKEN', '8678199814:AAECmOod8cH3GqKqgKnc7NdcmR1bAif2BBg'))

CHANNELS = {
    'hub':      int(os.environ.get('CHANNEL_POLYSHARK_HUB',      '-1003786930778')),  # Polyshark Alert Group
    'pro':      int(os.environ.get('CHANNEL_POLYSHARK_PRO',      '-1003739747776')),  # PolysharkPRO
    'sports':   int(os.environ.get('CHANNEL_POLYSHARK_SPORTS',   '-1003948034686')),
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
            q = json.loads(QUEUE_FILE.read_text())
            seen = set()
            deduped = []
            for item in q:
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

def format_card(bw, tier='PRO', channel_id=None):
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
      ✅ $X | ✅ +X% potential ROI = entry card
      ✅ $X | ✅ +X% ROI = realized win/close
      💰 $X | 💲 -X% ROI = loss + negative ROI both red

    Reject rules:
      Entry price $0.0000 → REJECT (return None)
      Stock tickers (AMAZON, YELLEN, MSFT etc) → REJECT (return None)
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

    # ── REJECT: already-resolved markets ────────────────────────────────
    end_date_str = getattr(bw, 'end_date', '') or ''
    if end_date_str:
        try:
            from datetime import datetime, timezone
            end_dt = datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if end_dt < now:
                log.warning(f"REJECTED: already-resolved market {getattr(bw,'market_id','')} ended {end_date_str[:10]}")
                return None
        except (ValueError, TypeError):
            pass  # unparseable date, allow it

    # ── REJECT: future opened date (bad data — opened ts is in the future) ─
    ts_opened = getattr(bw, 'timestamp', None)
    if ts_opened:
        try:
            from datetime import datetime, timezone as tz
            opened_dt = datetime.fromtimestamp(ts_opened, tz=tz.utc)
            if opened_dt > datetime.now(tz.utc):
                log.warning(f"REJECTED: future opened date {getattr(bw,'market_id','')} ts={ts_opened} ({opened_dt.date()})")
                return None
        except (ValueError, TypeError, OSError):
            pass

    # ── Build card ───────────────────────────────────────────────────────────
    free_card = (tier == 'free')
    label     = 'FREE TEASER' if free_card else tier.upper()

    # Determine WIN (resolved) vs ENTRY (open/unresolved market)
    end_str = getattr(bw, 'end_date', '') or ''
    is_open = True
    if end_str:
        try:
            from datetime import datetime, timezone as tz
            end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00')).replace(tzinfo=tz.utc)
            is_open = end_dt > datetime.now(tz.utc)
        except:
            pass
    alert_type = 'WHALE ENTRY' if is_open else 'WHALE WIN'

    # Sport emoji detection
    q_lower = getattr(bw, 'market_question', '').lower()
    sport_emoji = ''
    if any(k in q_lower for k in ['mets','yankees','dodgers','athletics','rangers','red sox','cubs','sox','mariners','padres',' Rockies','brewers','phillies','marlins','diamondbacks','giants','nationals','orioles','astros','guardians','twins','tigers','reds']):
        sport_emoji = '⚾'
    elif any(k in q_lower for k in ['lakers','celtics','warriors','nba','basketball','knicks','hawks','spurs','bulls','heat','suns','bucks','76ers']):
        sport_emoji = '🏀'
    elif any(k in q_lower for k in ['nfl','bengals','ravens','cowboys','eagles','chiefs','packers','bills','patriots','nfl','football','super bowl']):
        sport_emoji = '🏈'
    elif any(k in q_lower for k in ['hockey','rangers','bruins','flyers','penguins','devils','avalanche','golden knights','kraken','jets','flyers','wings']):
        sport_emoji = '🏒'
    elif any(k in q_lower for k in ['ufc','mma','boxing','fight','spann','griffin','suarez','barcelos']):
        sport_emoji = '🥊'
    elif any(k in q_lower for k in ['tennis','wimbledon','us open','madrid open','australian open','serena','nadal','alcaraz']):
        sport_emoji = '🎾'
    elif any(k in q_lower for k in ['golf','masters','pga','Tiger Woods']):
        sport_emoji = '⛳'
    elif any(k in q_lower for k in ['soccer','fc','Real Madrid','Barcelona','Manchester','liverpool','chelsea','arsenal','leicester']):
        sport_emoji = '⚽'
    elif any(k in q_lower for k in ['ipl','cricket','delhi capitals','sunrisers','lucknow super','mumbai indians']):
        sport_emoji = '🏏'

    # Classification badge
    profit_val = getattr(bw, 'profit_usdc', 0) or 0
    roi_val    = getattr(bw, 'roi_pct', 0) or 0
    wr_val     = getattr(bw, 'win_rate', 0) or 0
    streak_val = getattr(bw, 'win_streak', 0) or 0
    size_val   = getattr(bw, 'trade_size_usdc', 0) or 0

    classification_badge = ''
    if wr_val >= 65 and streak_val >= 3: classification_badge = '⚡ Elite Pick'
    elif streak_val >= 5:               classification_badge = '🔥 Hot Streak!'
    elif wr_val >= 65:                  classification_badge = '🏆 High Win-Rate'
    elif profit_val >= 100000:          classification_badge = '💰 Six-Figure Profit'
    elif size_val >= 100000:            classification_badge = '🐋 Whale Alert'

    # Sport emoji detection
    q_lower = getattr(bw, 'market_question', '').lower()  # for sport emoji detection
    sport_emoji = ''
    if any(k in q_lower for k in ['mets','yankees','dodgers','athletics','rangers','red sox','cubs','sox','mariners','padres',' Rockies','brewers','phillies','marlins','diamondbacks','giants','nationals','orioles','astros','guardians','twins','tigers','reds']):
        sport_emoji = '⚾'
    elif any(k in q_lower for k in ['lakers','celtics','warriors','nba','basketball','knicks','hawks','spurs','bulls','heat','suns','bucks','76ers']):
        sport_emoji = '🏀'
    elif any(k in q_lower for k in ['nfl','football','super bowl','cowboys','eagles','chiefs','packers','bills','patriots','bengals','ravens']):
        sport_emoji = '🏈'
    elif any(k in q_lower for k in ['hockey','rangers','bruins','flyers','penguins','devils','avalanche','golden knights','kraken','jets','flyers','wings','predators','sabres']):
        sport_emoji = '🏒'
    elif any(k in q_lower for k in ['ufc','mma','boxing','fight','spann','griffin','suarez','barcelos']):
        sport_emoji = '🥊'
    elif any(k in q_lower for k in ['tennis','wimbledon','us open','madrid open','australian open','serena','nadal','alcaraz']):
        sport_emoji = '🎾'
    elif any(k in q_lower for k in ['golf','masters','pga','Tiger Woods']):
        sport_emoji = '⛳'
    elif any(k in q_lower for k in ['soccer','fc','Real Madrid','Barcelona','Manchester','liverpool','chelsea','arsenal','leicester',' IPL','cricket','delhi capitals','sunrisers']):
        sport_emoji = '⚽'
    elif any(k in q_lower for k in ['ipl','cricket','sunrisers hyderabad','lucknow super giants','mumbai indians']):
        sport_emoji = '🏏'

    # Header with 🏅 inline
    header = f'<b>🟢 {classification_badge} [{label}] 🏅</b>' if classification_badge else f'<b>🟢 {alert_type} [{label}] 🏅</b>'

    # Market question — truncate at 72 chars, prepend sport emoji
    q = getattr(bw, 'market_question', '?')[:72]
    market = f'<b>🏅 {sport_emoji} {q}</b>' if sport_emoji else f'<b>🏅 {q}</b>'

    # Direction + explicit play target (v2.1)
    q = getattr(bw, 'market_question', '') or ''
    q_main = q.replace('🏅', '').strip()
    if ' vs. ' in q_main:
        left, right = q_main.split(' vs. ', 1)
    elif ' vs ' in q_main:
        left, right = q_main.split(' vs ', 1)
    else:
        left, right = q_main, ''
    left_t  = left.strip(' -–—:').strip()
    right_t = right.strip(' -–—:').strip()
    yes_target = f'{left_t} WIN' if left_t else 'THE LEFT SIDE WIN'
    no_target  = f'{right_t} WIN' if right_t else 'THE RIGHT SIDE WIN'
    direction = getattr(bw, 'outcome', '') or ''
    if direction.upper().startswith(('DOWN', 'NO')):
        bet = f'<b>🎯 ⬇️ BET NO — {no_target}</b>'
    else:
        bet = f'<b>🎯 ⬆️ BET YES — {yes_target}</b>'

    # ── Profit / ROI — both green or both red ────────────────────────────
    profit_usdc = getattr(bw, 'profit_usdc', 0) or 0
    roi_pct     = getattr(bw, 'roi_pct', 0) or 0
    if profit_usdc >= 0:
        roi_label = 'potential ROI' if getattr(bw, 'is_open', True) else 'ROI'
        profit = f'✅ <b>${profit_usdc:,.0f}</b> | <b>✅ +{roi_pct:.0f}% {roi_label}</b>'
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

    # Compute confidence score (0-100)
    profit_val = getattr(bw, 'profit_usdc', 0) or 0
    roi_val    = getattr(bw, 'roi_pct', 0) or 0
    wr_val     = getattr(bw, 'win_rate', 0) or 0
    streak_val = getattr(bw, 'win_streak', 0) or 0
    size_val   = getattr(bw, 'trade_size_usdc', 0) or 0

    score  = min(100, int(
        (20 if profit_val >= 50000 else 10 if profit_val >= 10000 else 5) +
        (20 if roi_val >= 100 else 15 if roi_val >= 50 else 8) +
        (20 if wr_val >= 65 else 10 if wr_val >= 45 else 3) +
        (15 if streak_val >= 5 else 8 if streak_val >= 3 else 0) +
        (15 if size_val >= 50000 else 10 if size_val >= 10000 else 0)
    ))
    conf_lbl = f'[Confidence: {score}%]'

    roi_lt = getattr(bw, 'roi_pct', 0) or 0
    roi_lbl = f'✅ ${abs(roi_lt):,.0f} P/L' if roi_lt >= 0 else f'💲 ${abs(roi_lt):,.0f} P/L'
    wr_parts = []
    if wr_lt > 0:
        wr_parts.append(f'{lt_badge} {lt_str} Wallet WR')
    else:
        wr_parts.append('🏆 -- Wallet WR')
    if wr_30 > 0:
        wr_parts.append(f'{wr30_badge} {wr30_str} 30D WR')
    else:
        wr_parts.append('🏆 -- 30D WR')
    if n_trades > 0:
        wr_parts.append(f'n={n_trades}')
    wr = ' | '.join(wr_parts)
    wr2_parts = [conf_lbl, roi_lbl]
    wr2 = ' | '.join(wr2_parts)

    # ── Streak ───────────────────────────────────────────────────────────────
    streak = getattr(bw, 'win_streak', 0) or 0
    if streak >= 8:
        streak_badge = '🔥🔥 ON FIRE 🔥🔥'
    elif streak >= 5:
        streak_badge = f'🔥 {streak}-win streak'
    else:
        streak_badge = ''

    # ── Wallet label (🐋 not 👤) ────────────────────────────────────────────
    def _ellipsize_wallet(addr: str) -> str:
        if not addr:
            return '0x....'
        if len(addr) <= 12:
            return addr
        return f'{addr[:6]}...{addr[-5:]}'

    trader_wallet = _ellipsize_wallet(getattr(bw, 'wallet', ''))
    wallet_url = f'https://polymarket.com/@{getattr(bw, "wallet", "").lower()}' if getattr(bw, 'wallet', '') else ''
    trader = f'🐋 [{trader_wallet}]({wallet_url}) 🌊' if wallet_url else f'🐋 {trader_wallet} 🌊'

    # No separate visible URL line; the wallet text itself carries the hyperlink.
    link = ''

    # ── Dates + wallet % of leaderboard ─────────────────────────────────────
    trade_ts   = getattr(bw, 'timestamp', None)
    trade_date = dt.datetime.fromtimestamp(trade_ts, tz=dt.timezone.utc).strftime('%b-%d-%y') if trade_ts else '?'
    end_date   = dt.datetime.fromisoformat(end_date_str.replace('Z', '+00:00')).strftime('%b-%d-%y') if end_date_str else '?'
    vol        = getattr(bw, 'leaderboard_volume', 0) or 0
    wallet_pct = f' ({size / vol * 100:.1f}% of wallet)' if vol and vol > 0 else ''
    dates      = f'📅 O: {trade_date} | Closing: {end_date}{wallet_pct}' if is_open else f'📅 O: {trade_date} | Resolved: {end_date}{wallet_pct}'

    # ── Assemble ─────────────────────────────────────────────────────────────
    sep = '————————————————————————'
    if free_card:
        lines = [header, sep, market, sep, profit, size_line, '', bet, dates, sep]
    else:
        lines = [header, sep, market, sep, profit, size_line, '', bet, dates]
        if wr:           lines.append(wr)
        if wr2:          lines.append(wr2)
        if streak_badge: lines.append(streak_badge)
        lines += [sep, trader]
    return '\n'.join(str(x) for x in lines)





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
            bw = bw_from_item(item)
            if bw is None:
                log.info(f'PRO filtered (resolved/null): {item["question"][:40]}')
                item['pro_sent'] = True
                dirty = True
                continue

            # CLOB validation for queued items (check once per item)
            if not item.get('_clob_validated'):
                enriched = validate_and_enrich(bw)
                if enriched is None:
                    log.info(f'CLOB rejected queued item: {item.get("market_id","")[:20]}...')
                    item['pro_sent'] = True  # mark sent so it won't reprocess
                    dirty = True
                    continue
                item['_clob_validated'] = True
            card = format_card(bw, 'pro', CHANNELS['hub'])
            if card:
                send(CHANNELS['hub'], card)
                log.info(f'PRO delay fired: {item["question"][:40]}')
                item['pro_sent'] = True
                dirty = True
            else:
                log.info(f'PRO filtered (null card): {item["question"][:40]}')
                item['pro_sent'] = True
                dirty = True

        # Category routing is hub-only now.
        # The Hub is the intake/router; no direct category sends from this daemon.
        if cat_ready and item.get('cat_sent') != item['cats']:
            item['cat_sent'] = item['cats']
            dirty = True
            log.info(f'Category routing deferred to Hub for: {item["question"][:40]}')

        # ⚡ Free channel disabled during v2.0 rollout: Hub + PRO only.
        # ⚠️ Keep queued items for downstream review, but do not emit to free channels.
        curated_ready = (now - queued_at) >= CURATED_DELAY
        free_ready    = (now - queued_at) >= FREE_DELAY
        item_ready    = curated_ready if item.get('is_curated') else free_ready

        if item_ready and not item.get('free_sent'):
            log.info(f'FREE disabled during rollout; retaining queued item: {item["question"][:40]}')
            item['free_sent'] = True
            continue  # drop from queue without sending

        updated.append(item)

    if dirty or len(updated) < len(queue):
        save_queue(updated)

def bw_from_item(item):
    """Reconstruct a minimal object from queued item. Returns None if market is resolved."""
    from datetime import datetime, timezone as _tz

    # Safety: reject already-resolved markets at format time
    end = item.get('end_date', '')
    if end:
        try:
            end_dt = datetime.fromisoformat(end.replace('Z', '+00:00')).replace(tzinfo=_tz.utc)
            if end_dt < datetime.now(_tz.utc):
                return None  # resolved, don't show
        except (ValueError, TypeError):
            pass

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
    bw.is_curated          = item.get('is_curated', False)
    bw.win_rate            = getattr(bw, 'win_rate', 0) or 0
    bw.win_rate_30d        = getattr(bw, 'win_rate_30d', 0) or 0
    bw.total_positions      = getattr(bw, 'total_positions', 0) or 0
    bw.win_streak          = getattr(bw, 'win_streak', 0) or 0

    # Look up wallet profile for real win rate / streak / trade count
    import os, sqlite3
    wp_path = os.path.join(os.path.dirname(__file__), '__pycache__', '..', 'wallet_profiles.json')
    if not os.path.exists(wp_path):
        wp_path = '/tmp/wallet_profiles.json'
    loaded_profile = False
    if os.path.exists(wp_path):
        try:
            wps = _json.loads(open(wp_path).read())
            waddr = (bw.wallet or '').lower()
            if waddr in wps:
                wp = wps[waddr]
                bw.win_rate        = wp.get('win_rate', 0) or 0
                bw.win_rate_30d    = wp.get('win_rate_30d', 0) or 0
                bw.total_positions = wp.get('total_positions', 0) or 0
                bw.win_streak      = wp.get('current_streak', 0) or 0
                loaded_profile = True
        except Exception:
            pass
    if not loaded_profile:
        try:
            db_path = '/home/ubuntu/.openclaw/workspace/repos/whaletrax/wallet_tracker.db'
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                row = conn.execute('SELECT total_pnl, win_rate_pct, roi_30d, total_positions FROM tracked_wallets WHERE wallet_address=?', ((bw.wallet or '').lower(),)).fetchone()
                conn.close()
                if row:
                    # prefer the live wallet tracker if available
                    bw.win_rate        = row[1] or bw.win_rate or 0
                    bw.win_rate_30d    = row[2] or bw.win_rate_30d or 0
                    bw.total_positions = row[3] or bw.total_positions or 0
        except Exception:
            pass

    # Fallback: from item
    bw.win_rate        = bw.win_rate        or item.get('win_rate', 0)
    bw.win_rate_30d    = bw.win_rate_30d    or item.get('win_rate_30d', 0)
    bw.total_positions = bw.total_positions or item.get('total_positions', 0)
    bw.win_streak     = bw.win_streak      or item.get('win_streak', 0)
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

    # ── CLOB Validation: reject closed/already-started markets ────────
    validated_bws = []
    for bw in new_bws:
        enriched = validate_and_enrich(bw)
        if enriched is None:
            log.info(f"CLOB rejected: {bw.market_id[:20]}...")
            continue
        validated_bws.append(bw)
    skipped = len(new_bws) - len(validated_bws)
    new_bws = validated_bws
    log.info(f"CLOB validation: {len(new_bws)} passed, {skipped} rejected")

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
        log.info(f'Queued: {bw.market_question[:50]} -> cats={cats} | curated in {CURATED_DELAY} | free in {FREE_DELAY}')

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
        _time.sleep(120)  # 2 min router poll interval
