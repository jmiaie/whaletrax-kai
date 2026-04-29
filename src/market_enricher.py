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

def validate_and_enrich(bw) -> Optional[dict]:
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
        return None  # can't validate — let it through (fail open)

    now = datetime.now(timezone.utc)

    # NOTE: game_start_time check removed — too strict for short-duration markets
    # NOTE: closed=True check removed — historical closed markets flow through per Jeff

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

    # Enrich with real data
    return {
        'market_id': market_id,
        'question': info.get('question', ''),
        'game_start_time': info.get('game_start_time', ''),
        'closed': info.get('closed', False),
        'accepting_orders': info.get('accepting_orders', False),
        'tokens': info.get('tokens', []),
        'winner': next((t.get('outcome','') for t in info.get('tokens',[]) if t.get('winner')), ''),
    }