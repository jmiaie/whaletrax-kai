#!/usr/bin/env python3
"""
Polyshark Webhook Receiver
Receives Stripe + PayPal webhooks at:
  https://api.polyshark.io/webhook/stripe
  https://api.polyshark.io/webhook/paypal

Verifies signatures, records payments, auto-approves subscribers.

Security model (fail closed):
  * Stripe: STRIPE_WEBHOOK_SECRET must be set (else HTTP 503) and every
    request must carry a valid Stripe-Signature header (else HTTP 400).
  * PayPal: every event is verified with PayPal's verify-webhook-signature
    API. Requires PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET and PAYPAL_WEBHOOK_ID
    (PAYPAL_API_BASE defaults to the live API). If any is missing, or
    verification fails for any reason, the event is refused and no access is
    granted.

Configuration is loaded lazily (never at import time):
  POLYSHARK_BOT_TOKEN      Telegram bot token (preferred), or
  POLYSHARK_TOKEN_FILE     file containing a line like TOKEN=... (defaults to
                           the original credentials path below)
  POLYSHARK_DB_PATH        SQLite DB path (defaults to the original path)
  POLYSHARK_WEBHOOK_LOG    log file path (default /tmp/polyshark_webhook.log)
"""

import os, json, hmac, hashlib, logging, sys, time
from datetime import datetime, timedelta
from http import HTTPStatus
from pathlib import Path

# Paths (defaults; overridable via env, resolved lazily)
CRED_DIR   = Path('/home/ubuntu/.openclaw/workspace/credentials')
LOG_FILE   = Path(os.environ.get('POLYSHARK_WEBHOOK_LOG', '/tmp/polyshark_webhook.log'))
DEFAULT_DB_PATH    = Path('/home/ubuntu/.openclaw/workspace/polyshark_subs.db')
DEFAULT_TOKEN_FILE = Path('/home/ubuntu/.openclaw/workspace/credentials/skey-telegram-jefe-swarm2bot')

STRIPE_TOLERANCE_SECONDS = 300  # same default tolerance as Stripe's own libraries


class ConfigError(RuntimeError):
    """Raised when required runtime configuration is missing."""


_token_cache = None


def get_bot_token() -> str:
    """Return the Telegram bot token, loading it on first use (not at import)."""
    global _token_cache
    if _token_cache:
        return _token_cache
    env_token = os.environ.get('POLYSHARK_BOT_TOKEN', '').strip()
    if env_token:
        _token_cache = env_token
        return _token_cache
    token_file = Path(os.environ.get('POLYSHARK_TOKEN_FILE', str(DEFAULT_TOKEN_FILE)))
    try:
        with open(token_file) as f:
            lines = [l for l in f.read().split('\n') if '=' in l and 'TOKEN' in l]
    except OSError as e:
        raise ConfigError(
            f"Telegram bot token not configured: set POLYSHARK_BOT_TOKEN or "
            f"POLYSHARK_TOKEN_FILE (could not read {token_file}: {e})") from e
    if not lines:
        raise ConfigError(f"No TOKEN=... line found in {token_file}")
    _token_cache = lines[0].split('=', 1)[1].strip()
    return _token_cache


def get_db_path() -> Path:
    return Path(os.environ.get('POLYSHARK_DB_PATH', str(DEFAULT_DB_PATH)))


# Channel IDs
CHANNELS = {
    'polyshark':   -1003999194095,  # Free tier (delayed 4-6h)
    'pro':         -1003739747776,   # PolysharkPro
    'sports':      -1003948034686,   # PolysharkSports
    'crypto':      -1003999731708,   # PolysharkCrypto
    'weather':     -1003532326443,   # PolysharkWeather
    'world':       -1003927756388,   # PolysharkWorld
    'politics':    -1003935178097,   # PolysharkPolitics
    'econ':        -1003868008293,   # PolysharkEcon
    'chat':        -1003860830659,   # Our Team (no tier)
}

# Tier -> category mapping
CATEGORY_CHANNELS = {
    'sports':   -1003948034686,
    'crypto':   -1003999731708,
    'weather':  -1003532326443,
    'world':    -1003927756388,
    'politics': -1003935178097,
    'econ':     -1003868008293,
}

TIER_PRICES = {
    'pro':     50.00,   # USD/month
    'sports':  30.00,
    'politics':30.00,
    'crypto':  30.00,
    'weather': 30.00,
}

import sqlite3
import requests

from polyshark_subs import add_subscriber, tier_from_price, is_all_channels, is_single_channel, CHANNELS

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger('polyshark_webhook')

# ── Header helper ─────────────────────────────────────────────────────────────
def _get_header(headers, name):
    """Case-insensitive header lookup ('Stripe-Signature' == 'STRIPE-SIGNATURE')."""
    if not headers:
        return None
    wanted = name.lower().replace('_', '-')
    for k, v in headers.items():
        if k.lower().replace('_', '-') == wanted:
            return v
    return None

# ── Stripe signature verification ──────────────────────────────────────────────
def verify_stripe_signature(payload: bytes, sig_header: str, secret: str,
                            tolerance: int = STRIPE_TOLERANCE_SECONDS, now=None) -> bool:
    """Verify a Stripe-Signature header per Stripe's documented scheme.

    Header format: ``t=<unix ts>,v1=<hex hmac>[,v1=<hex hmac>...][,v0=...]``.
    The signed payload is ``"<t>." + raw request body`` (raw bytes, unmodified),
    HMAC-SHA256 keyed with the endpoint secret. Any matching v1 signature is
    accepted (Stripe sends several during secret rotation). Comparison is
    constant-time. Timestamps outside +/- ``tolerance`` seconds are rejected.
    """
    if not secret or not sig_header or not isinstance(payload, (bytes, bytearray)):
        return False
    timestamp = None
    v1_sigs = []
    for item in sig_header.split(','):
        key, sep, value = item.strip().partition('=')
        if not sep:
            continue
        if key == 't':
            try:
                timestamp = int(value)
            except ValueError:
                return False
        elif key == 'v1' and value:
            v1_sigs.append(value)
    if timestamp is None or not v1_sigs:
        return False
    current = time.time() if now is None else now
    if abs(current - timestamp) > tolerance:
        log.warning("Stripe signature timestamp outside tolerance")
        return False
    signed_payload = str(timestamp).encode() + b'.' + bytes(payload)
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    matched = False
    for sig in v1_sigs:
        # Evaluate every candidate so timing does not reveal which one matched.
        if hmac.compare_digest(expected, sig):
            matched = True
    return matched

# ── PayPal signature verification ──────────────────────────────────────────────
PAYPAL_REQUIRED_HEADERS = (
    'PayPal-Auth-Algo', 'PayPal-Cert-Url', 'PayPal-Transmission-Id',
    'PayPal-Transmission-Sig', 'PayPal-Transmission-Time',
)


def paypal_verification_configured() -> bool:
    return all(os.environ.get(k, '').strip() for k in
               ('PAYPAL_CLIENT_ID', 'PAYPAL_CLIENT_SECRET', 'PAYPAL_WEBHOOK_ID'))


def verify_paypal_webhook(payload: bytes, headers, http=None) -> bool:
    """Verify a PayPal webhook via PayPal's verify-webhook-signature API.

    Returns True only if PayPal answers verification_status == 'SUCCESS'.
    Any missing configuration, missing header, network error or unexpected
    response returns False (fail closed). ``http`` is injectable for tests
    (defaults to the ``requests`` module).
    """
    if not paypal_verification_configured():
        log.error("PayPal webhook refused: PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET / "
                  "PAYPAL_WEBHOOK_ID not configured (see README, 'Polyshark webhook')")
        return False
    hdr = {name: _get_header(headers, name) for name in PAYPAL_REQUIRED_HEADERS}
    if not all(hdr.values()):
        log.error("PayPal webhook refused: missing PayPal transmission headers")
        return False
    http = http or requests
    base = os.environ.get('PAYPAL_API_BASE', 'https://api-m.paypal.com').rstrip('/')
    try:
        event = json.loads(payload)
        tok = http.post(f'{base}/v1/oauth2/token',
                        auth=(os.environ['PAYPAL_CLIENT_ID'], os.environ['PAYPAL_CLIENT_SECRET']),
                        data={'grant_type': 'client_credentials'}, timeout=10)
        access_token = tok.json().get('access_token')
        if not access_token:
            log.error("PayPal webhook refused: could not obtain PayPal access token")
            return False
        r = http.post(f'{base}/v1/notifications/verify-webhook-signature',
                      headers={'Authorization': f'Bearer {access_token}',
                               'Content-Type': 'application/json'},
                      json={
                          'auth_algo':         hdr['PayPal-Auth-Algo'],
                          'cert_url':          hdr['PayPal-Cert-Url'],
                          'transmission_id':   hdr['PayPal-Transmission-Id'],
                          'transmission_sig':  hdr['PayPal-Transmission-Sig'],
                          'transmission_time': hdr['PayPal-Transmission-Time'],
                          'webhook_id':        os.environ['PAYPAL_WEBHOOK_ID'],
                          'webhook_event':     event,
                      }, timeout=10)
        status = r.json().get('verification_status')
    except Exception as e:
        log.error(f"PayPal webhook refused: verification error: {e}")
        return False
    if status != 'SUCCESS':
        log.error(f"PayPal webhook refused: verification_status={status!r}")
        return False
    return True


def check_config():
    """Startup check: raise ConfigError with a clear message if misconfigured."""
    if not os.environ.get('STRIPE_WEBHOOK_SECRET', '').strip():
        raise ConfigError("STRIPE_WEBHOOK_SECRET is not set; Stripe webhooks would be refused")
    get_bot_token()
    if not paypal_verification_configured():
        log.warning("PayPal verification not configured; /webhook/paypal will refuse all events")

# ── DB helpers ────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn

def update_expiry(telegram_id, new_expiry, auto_pay=None):
    conn = get_db()
    now = datetime.utcnow().isoformat()
    if auto_pay is not None:
        conn.execute("UPDATE subscribers SET expiry_date=?, auto_pay=?, updated_at=? WHERE telegram_id=?",
                    [new_expiry, int(auto_pay), now, str(telegram_id)])
    else:
        conn.execute("UPDATE subscribers SET expiry_date=?, updated_at=? WHERE telegram_id=?",
                    [new_expiry, now, str(telegram_id)])
    conn.commit()
    conn.close()

def record_payment(telegram_id, amount, currency, payment_method, transaction_id):
    conn = get_db()
    now = datetime.utcnow().isoformat()
    conn.execute("""
        INSERT INTO payment_log (telegram_id, amount, currency, payment_method, transaction_id, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'completed', ?)
    """, [str(telegram_id), amount, currency, payment_method, transaction_id, now])
    conn.commit()
    conn.close()

# ── Telegram: send DM ─────────────────────────────────────────────────────────
def send_dm(telegram_id, text):
    try:
        r = requests.post(f'https://api.telegram.org/bot{get_bot_token()}/sendMessage',
            json={'chat_id': str(telegram_id), 'text': text, 'parse_mode': 'Markdown'},
            timeout=10)
        return r.json().get('ok', False)
    except Exception as e:
        log.error(f"DM failed for {telegram_id}: {e}")
        return False

# ── Telegram: create invite link ───────────────────────────────────────────────
def create_invite_link(channel_id, member_limit=1, name=''):
    try:
        r = requests.post(f'https://api.telegram.org/bot{get_bot_token()}/createChatInviteLink',
            json={
                'chat_id': str(channel_id),
                'member_limit': member_limit,  # one-time link, single use
                'name': name or f"sub_{datetime.utcnow().isoformat()[:10]}"
            },
            timeout=10)
        d = r.json()
        if d.get('ok'):
            return d['result']['invite_link']
        log.error(f"Failed to create invite link: {d}")
        return None
    except Exception as e:
        log.error(f"Create invite link error: {e}")
        return None

# ── Stripe webhook handler ─────────────────────────────────────────────────────
def handle_stripe_webhook(payload: bytes, headers):
    """Returns (http_status, body_dict)."""
    secret = os.environ.get('STRIPE_WEBHOOK_SECRET', '').strip()
    if not secret:
        log.error("STRIPE_WEBHOOK_SECRET not set - refusing Stripe webhook")
        return 503, {'error': 'Webhook not configured'}

    sig_header = _get_header(headers, 'Stripe-Signature')
    if not sig_header:
        log.error("Missing Stripe-Signature header - refusing Stripe webhook")
        return 400, {'error': 'Missing signature'}
    if not verify_stripe_signature(payload, sig_header, secret):
        log.error("Invalid Stripe signature")
        return 400, {'error': 'Invalid signature'}

    try:
        event = json.loads(payload)
    except ValueError:
        return 400, {'error': 'Invalid JSON'}
    event_type = event.get('type', '')
    log.info(f"Stripe webhook: {event_type}")
    
    if event_type == 'checkout.session.completed':
        session = event['data']['object']
        email = session.get('customer_email', '')
        # Derive tier from PRICE PAID (discount-proof, future-proof against price changes)
        amount_cents = session.get('amount_total', 0)
        tier = tier_from_price(amount_cents)
        if not tier:
            log.warning(f'No tier mapping for amount {amount_cents} — refund or unknown product')
            return 200, {'ok': True}
        tg_id = session.get('metadata', {}).get('telegram_id', '')
        channel_category = session.get('metadata', {}).get('channel_category', 'sports')
        auto_pay = session.get('mode') == 'subscription'

        if not tg_id:
            log.warning(f'No telegram_id in Stripe metadata for session {session.get("id")}')
            return 200, {'ok': True}

        # Record payment (amount_total is in cents)
        record_payment(tg_id, amount_cents / 100, session.get('currency', 'USD').upper(), 'stripe', session.get('id'))

        # Add/update subscriber
        add_subscriber(tg_id, email, tier, source='stripe', auto_pay=auto_pay, channel_category=channel_category)

        # Create invite link
        if is_single_channel(tier):
            chosen_cat = session.get('metadata', {}).get('channel_category', 'sports')
            channel_id = CHANNELS.get(chosen_cat, CHANNELS['hub'])
        elif is_all_channels(tier):
            channel_id = CHANNELS['hub']
        else:
            channel_id = CHANNELS['hub']
        invite_link = create_invite_link(channel_id)

        # Send DM
        price_map = {175000: 1750, 52800: 528, 33600: 336, 5500: 55, 3500: 35}
        price = price_map.get(amount_cents, 55)
        msg = (
            f'Payment confirmed - you\'re in!\n\n'
            f'Plan: Polyshark {tier} @ ${price}\n\n'
        )
        if invite_link:
            msg += f'Join here: {invite_link}'

        send_dm(tg_id, msg)
        return 200, {'ok': True}
    
    elif event_type == 'invoice.paid':
        # Renewal
        invoice = event['data']['object']
        tg_id = invoice.get('metadata', {}).get('telegram_id', '')
        if tg_id:
            new_expiry = (datetime.utcnow() + timedelta(days=30)).isoformat()[:10]
            update_expiry(tg_id, new_expiry, auto_pay=True)
            send_dm(tg_id, "Renewal confirmed - you're all set for another month!")
        return 200, {'ok': True}
    
    elif event_type == 'customer.subscription.deleted':
        sub = event['data']['object']
        tg_id = sub.get('metadata', {}).get('telegram_id', '')
        if tg_id:
            conn = get_db()
            conn.execute("UPDATE subscribers SET status='cancelled' WHERE telegram_id=?", [str(tg_id)])
            conn.commit()
            conn.close()
            send_dm(tg_id, "Subscription cancelled. You've been removed from Polyshark channels.")
        return 200, {'ok': True}
    
    return 200, {'ok': True}

# ── PayPal webhook handler ─────────────────────────────────────────────────────
def handle_paypal_webhook(payload: bytes, headers):
    """Returns (http_status, body_dict). Never acts on an unverified event."""
    try:
        json.loads(payload)
    except ValueError:
        return 400, {'error': 'Invalid JSON'}
    if not verify_paypal_webhook(payload, headers):
        return 400, {'error': 'Unverified PayPal event'}
    event = json.loads(payload)
    event_type = event.get('event_type', '')
    resource = event.get('resource', {})
    log.info(f"PayPal webhook: {event_type}")
    
    if event_type == 'PAYMENT.SALE.COMPLETED':
        tg_id = resource.get('custom_id', '')
        amount = float(resource.get('amount', {}).get('total', 0))
        currency = resource.get('amount', {}).get('currency', 'USD')
        tx_id = resource.get('id', '')
        
        if tg_id and amount > 0:
            record_payment(tg_id, amount, currency, 'paypal', tx_id)
            # Assume one-time payment = 30 days unless specified
            add_subscriber(tg_id, '', 'pro', 'paypal', auto_pay=False)
            
            invite_link = create_invite_link(CHANNELS['hub'])  # 'hub' == PolysharkPro (polyshark_subs.CHANNELS)
            msg = f"Payment confirmed via PayPal - you're in! Join: {invite_link or 'check back shortly'}"
            send_dm(tg_id, msg)
        
        return 200, {'ok': True}
    
    elif event_type == 'BILLING.SUBSCRIPTION.CANCELLED':
        tg_id = resource.get('custom_id', '')
        if tg_id:
            conn = get_db()
            conn.execute("UPDATE subscribers SET status='cancelled' WHERE telegram_id=?", [str(tg_id)])
            conn.commit()
            conn.close()
            send_dm(tg_id, "Subscription cancelled.")
        return 200, {'ok': True}
    
    return 200, {'ok': True}

# ── WSGI app (for the webhook endpoint) ───────────────────────────────────────
MAX_BODY_BYTES = 1024 * 1024


def _read_body(environ) -> bytes:
    try:
        length = int(environ.get('CONTENT_LENGTH') or 0)
    except ValueError:
        length = 0
    length = max(0, min(length, MAX_BODY_BYTES))
    return environ['wsgi.input'].read(length) if length else b''


def _request_headers(environ):
    """HTTP_FOO_BAR -> 'foo-bar' (lower-case; look up with _get_header)."""
    return {k[5:].replace('_', '-').lower(): v
            for k, v in environ.items() if k.startswith('HTTP_')}


def _respond(start_response, status, body):
    try:
        phrase = HTTPStatus(status).phrase
    except ValueError:
        phrase = 'Error'
    start_response(f'{status} {phrase}', [('Content-Type', 'application/json')])
    return [json.dumps(body).encode()]


def app(environ, start_response):
    path = environ.get('PATH_INFO', '')
    method = environ.get('REQUEST_METHOD', 'GET')

    if path.startswith('/webhook/stripe') and method == 'POST':
        status, body = handle_stripe_webhook(_read_body(environ), _request_headers(environ))
        return _respond(start_response, status, body)

    elif path.startswith('/webhook/paypal') and method == 'POST':
        status, body = handle_paypal_webhook(_read_body(environ), _request_headers(environ))
        return _respond(start_response, status, body)

    elif path == '/health' or path == '/':
        return _respond(start_response, 200, {'status': 'ok'})

    else:
        return _respond(start_response, 404, {'error': 'not found'})

if __name__ == '__main__':
    # Quick test
    print("Stripe webhook endpoint: /webhook/stripe")
    print("PayPal webhook endpoint: /webhook/paypal")
    print("Health check: /health")
    print("Set STRIPE_WEBHOOK_SECRET env var before production use")
