#!/usr/bin/env python3
"""
Polyshark Webhook Receiver
Receives Stripe + PayPal webhooks at:
  https://api.polyshark.io/webhook/stripe
  https://api.polyshark.io/webhook/paypal

Verifies signatures, records payments, auto-approves subscribers.
"""

import os, json, hmac, hashlib, logging, sys
from datetime import datetime, timedelta
from pathlib import Path

# Paths
CRED_DIR   = Path('/home/ubuntu/.openclaw/workspace/credentials')
LOG_FILE   = Path('/tmp/polyshark_webhook.log')
DB_PATH    = Path('/home/ubuntu/.openclaw/workspace/polyshark_subs.db')
TOKEN_FILE = Path('/home/ubuntu/.openclaw/workspace/credentials/skey-telegram-jefe-swarm2bot')

# Telegram bot token
with open(TOKEN_FILE) as f:
    token = [l.split('=')[1].strip() for l in f.read().split('\n') if '=' in l and 'TOKEN' in l][0]

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

# ── Stripe signature verification ──────────────────────────────────────────────
def verify_stripe_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    try:
        import time
        t, v1 = sig_header.split(',')
        if not t.startswith('t=') or not v1.startswith('v1='):
            return False
        timestamp = int(t[2:])
        if abs(time.time() - timestamp) > 300:
            return False  # stale
        signed_payload = f"{timestamp}.{payload.decode()}"
        expected = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, v1[3:])
    except Exception as e:
        log.error(f"Stripe signature verification failed: {e}")
        return False

# ── DB helpers ────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def add_subscriber(telegram_id, username, tier, payment_method, auto_pay=False, expiry_days=30):
    conn = get_db()
    now = datetime.utcnow().isoformat()
    expiry = (datetime.utcnow() + timedelta(days=expiry_days)).isoformat()[:10]
    try:
        conn.execute("""
            INSERT INTO subscribers (telegram_id, username, tier, status, auto_pay, payment_method, expiry_date, created_at, updated_at)
            VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?)
        """, [str(telegram_id), username, tier, int(auto_pay), payment_method, expiry, now, now])
        conn.commit()
        log.info(f"Added subscriber: {telegram_id} tier={tier}")
    except sqlite3.IntegrityError:
        conn.execute("UPDATE subscribers SET status='active', tier=?, payment_method=?, expiry_date=?, updated_at=? WHERE telegram_id=?",
                    [tier, payment_method, expiry, now, str(telegram_id)])
        conn.commit()
        log.info(f"Re-activated subscriber: {telegram_id}")
    finally:
        conn.close()

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
        r = requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': str(telegram_id), 'text': text, 'parse_mode': 'Markdown'},
            timeout=10)
        return r.json().get('ok', False)
    except Exception as e:
        log.error(f"DM failed for {telegram_id}: {e}")
        return False

# ── Telegram: create invite link ───────────────────────────────────────────────
def create_invite_link(channel_id, member_limit=1, name=''):
    try:
        r = requests.post(f'https://api.telegram.org/bot{token}/createChatInviteLink',
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
    secret = os.environ.get('STRIPE_WEBHOOK_SECRET', '').strip()
    if not secret:
        log.warning("STRIPE_WEBHOOK_SECRET not set - skipping signature verification")
    
    if secret and headers.get('Stripe-Signature'):
        if not verify_stripe_signature(payload, headers['Stripe-Signature'], secret):
            log.error("Invalid Stripe signature")
            return {'error': 'Invalid signature'}, 400
    
    event = json.loads(payload)
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
            return {'ok': True}
        tg_id = session.get('metadata', {}).get('telegram_id', '')
        channel_category = session.get('metadata', {}).get('channel_category', 'sports')
        auto_pay = session.get('mode') == 'subscription'

        if not tg_id:
            log.warning(f'No telegram_id in Stripe metadata for session {session.get("id")}')
            return {'ok': True}

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
        return {'ok': True}
    
    elif event_type == 'invoice.paid':
        # Renewal
        invoice = event['data']['object']
        tg_id = invoice.get('metadata', {}).get('telegram_id', '')
        if tg_id:
            new_expiry = (datetime.utcnow() + timedelta(days=30)).isoformat()[:10]
            update_expiry(tg_id, new_expiry, auto_pay=True)
            send_dm(tg_id, "Renewal confirmed - you're all set for another month!")
        return {'ok': True}
    
    elif event_type == 'customer.subscription.deleted':
        sub = event['data']['object']
        tg_id = sub.get('metadata', {}).get('telegram_id', '')
        if tg_id:
            conn = get_db()
            conn.execute("UPDATE subscribers SET status='cancelled' WHERE telegram_id=?", [str(tg_id)])
            conn.commit()
            conn.close()
            send_dm(tg_id, "Subscription cancelled. You've been removed from Polyshark channels.")
        return {'ok': True}
    
    return {'ok': True}

# ── PayPal webhook handler ─────────────────────────────────────────────────────
def handle_paypal_webhook(payload: bytes, headers):
    # PayPal verifies via IPN or their own signature
    # For now, trust the payload if it has the right event type
    try:
        event = json.loads(payload)
    except:
        return {'error': 'Invalid JSON'}, 400
    
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
            
            invite_link = create_invite_link(CHANNELS['pro'])
            msg = f"Payment confirmed via PayPal - you're in! Join: {invite_link or 'check back shortly'}"
            send_dm(tg_id, msg)
        
        return {'ok': True}
    
    elif event_type == 'BILLING.SUBSCRIPTION.CANCELLED':
        tg_id = resource.get('custom_id', '')
        if tg_id:
            conn = get_db()
            conn.execute("UPDATE subscribers SET status='cancelled' WHERE telegram_id=?", [str(tg_id)])
            conn.commit()
            conn.close()
            send_dm(tg_id, "Subscription cancelled.")
        return {'ok': True}
    
    return {'ok': True}

# ── WSGI app (for the webhook endpoint) ───────────────────────────────────────
def app(environ, start_response):
    import cgi
    
    path = environ.get('PATH_INFO', '')
    method = environ.get('REQUEST_METHOD', 'GET')
    
    if path.startswith('/webhook/stripe') and method == 'POST':
        # Read payload
        content_length = int(environ.get('CONTENT_LENGTH', 0))
        payload = environ['wsgi.input'].read(content_length)
        
        # Get Stripe signature header
        stripe_headers = {
            k.replace('HTTP_', '').replace('_', '-'): v
            for k, v in environ.items()
            if k.startswith('HTTP_STRIPE_') or k == 'HTTP_STRIPE_SIGNATURE'
        }
        
        status, body = handle_stripe_webhook(payload, stripe_headers)
        body_json = json.dumps(body).encode()
        start_response(f'{status} OK' if status == 200 else f'{status} Error',
                       [('Content-Type', 'application/json')])
        return [body_json]
    
    elif path.startswith('/webhook/paypal') and method == 'POST':
        content_length = int(environ.get('CONTENT_LENGTH', 0))
        payload = environ['wsgi.input'].read(content_length)
        
        paypal_headers = {
            k.replace('HTTP_', '').replace('_', '-'): v
            for k, v in environ.items()
            if k.startswith('HTTP_PAYPAL_')
        }
        
        status, body = handle_paypal_webhook(payload, paypal_headers)
        body_json = json.dumps(body).encode()
        start_response(f'{status} OK' if status == 200 else f'{status} Error',
                       [('Content-Type', 'application/json')])
        return [body_json]
    
    elif path == '/health' or path == '/':
        start_response('200 OK', [('Content-Type', 'application/json')])
        return [b'{"status": "ok"}']
    
    else:
        start_response('404 Not Found', [('Content-Type', 'application/json')])
        return [b'{"error": "not found"}']

if __name__ == '__main__':
    # Quick test
    print("Stripe webhook endpoint: /webhook/stripe")
    print("PayPal webhook endpoint: /webhook/paypal")
    print("Health check: /health")
    print("Set STRIPE_WEBHOOK_SECRET env var before production use")
