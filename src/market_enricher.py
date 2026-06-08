"""Enrich big win data with Polymarket CLOB API validation."""
import requests, logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)
CLOB_BASE = "https://clob.polymarket.com"

def get_market_info(market_id: str) -> Optional[dict]:
    """Fetch market info from Polymarket CLOB. Returns None on failure."""
    try:
        r = requests.get(f"{CLOB_BASE}/markets/{market_id}", timeout=8)
        if r.status_code == 200:
            return r.json()
        log.warning(f"CLOB API status {r.status_code} for {market_id}")
        return None
    except Exception as e:
        log.warning(f"CLOB fetch failed for {market_id}: {e}")
        return None

def validate_and_enrich(bw):
    """
    Validate a big win against CLOB API.
    Returns None (reject) or enriched dict with validated fields.
    Jeff approved: historical closed markets AND short-duration markets (crypto binaries)
    are allowed through. Only block future-opened ts (proven bad data).
    """
    market_id = getattr(bw, 'market_id', '')
    if not market_id:
        return None

    info = get_market_info(market_id)
    if not info:
        return None  # can't validate — fail open

    now = datetime.now(timezone.utc)

    # REJECT if ts_opened is in the future (bad data — Polymarket API glitch)
    ts_opened = getattr(bw, 'timestamp', None)
    if ts_opened:
        try:
            ts_dt = datetime.fromtimestamp(ts_opened, tz=timezone.utc)
            if ts_dt > now:
                log.info(f"REJECT: future-opened ts={ts_opened} ({ts_dt.date()}) market={market_id[:20]}...")
                return None
        except (ValueError, TypeError, OSError):
            pass

    # Extract YES and NO token prices for current pricing context
    tokens = info.get('tokens', []) or []
    yes_price = None
    no_price = None
    yes_outcome = None
    no_outcome = None
    winner = ''
    for t in tokens:
        p = float(t.get('price', 0) or 0)
        o = str(t.get('outcome', '') or '').strip()
        w = bool(t.get('winner', False))
        # Use outcome string as primary key — "Yes" → yes_price, "No" → no_price
        # For team-name markets (neither "Yes" nor "No"), fall back to price heuristic
        if o == 'Yes':
            yes_price = p
            yes_outcome = o
        elif o == 'No':
            no_price = p
            no_outcome = o
        else:
            # Team-name or exotic market — use price level as fallback heuristic
            if p > 0.5 and yes_price is None:
                yes_price = p
                yes_outcome = o
            elif p <= 0.5 and no_price is None:
                no_price = p
                no_outcome = o
        if w:
            winner = o

    game_start = info.get('game_start_time', '') or ''

    # Format game start time → "Sun 11:10 PM UTC"
    start_fmt = ''
    if game_start:
        try:
            dt = datetime.fromisoformat(game_start.replace('Z', '+00:00')).replace(tzinfo=timezone.utc)
            start_fmt = dt.strftime('%a %-I:%M %p %Z')
        except Exception:
            start_fmt = game_start[:16]

    # Format slug → "MLB · KC vs CIN · 06/01"
    slug_raw = info.get('market_slug', '') or ''
    slug_parts = slug_raw.replace('-', ' ').split()
    if len(slug_parts) >= 6:
        slug_fmt = f"{slug_parts[0].upper()} · {slug_parts[1].upper()} vs {slug_parts[2].upper()} · {slug_parts[4]}/{slug_parts[5]}"
    else:
        slug_fmt = slug_raw.replace('-', ' ')

    # Determine geo-availability from CLOB signals:
    # - neg_risk=True → Neg Risk market (US-accessible via CLOB) = GLOBAL
    # - neg_risk=False → standard Polyshark market, check slug pattern
    is_neg_risk = bool(info.get('neg_risk', False))
    accepting = bool(info.get('accepting_orders', False))

    slug_lower = slug_raw.lower()
    global_slugs = ['nba', 'nfl', 'nhl', 'mlb', 'ncaa', 'ufc', 'tennis', 'golf',
                    'soccer', 'f1', 'formula', 'mma', 'boxing', 'cricket',
                    'rugby', 'world series', 'playoffs', 'championship']
    us_only_slugs = ['bitcoin', 'eth', 'solana', 'nft', 'defi',
                     '$aapl', '$tsla', '$nvda', 'stock ticker', 'spot etf',
                     'bitcoin etf', 'ethereum etf']

    if is_neg_risk:
        geo_available = 'GLOBAL'  # Neg Risk markets are US-accessible
    elif any(g in slug_lower for g in global_slugs):
        geo_available = 'GLOBAL'  # Sports leagues = globally available
    elif any(g in slug_lower for g in us_only_slugs):
        geo_available = 'NON_US_ONLY'  # Finance/crypto markets = geo-restricted
    else:
        geo_available = 'GLOBAL'  # Default: open CLOB markets are global

    return {
        'market_id': market_id,
        'question': info.get('question', ''),
        'game_start_time': game_start,
        'game_start_fmt': start_fmt,
        'closed': info.get('closed', False),
        'accepting_orders': accepting,
        'neg_risk': is_neg_risk,
        'tokens': tokens,
        'winner': winner,
        'yes_price': yes_price,
        'no_price': no_price,
        'yes_outcome': yes_outcome,
        'no_outcome': no_outcome,
        'market_slug': slug_fmt,
        'description': (info.get('description') or '')[:300],
        'geo_available': geo_available,
    }