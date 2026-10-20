#!/usr/bin/env python3
"""Tests for polyshark_webhook. Stdlib unittest; runs anywhere, no network.

    python -m unittest test_webhook -v      (or: python -m pytest test_webhook.py)
"""
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault('POLYSHARK_WEBHOOK_LOG', os.path.join(tempfile.gettempdir(), 'polyshark_webhook_test.log'))

import polyshark_webhook as wh  # must import cleanly with no token file present

TEST_SECRET = 'whsec_test_secret_for_unit_tests'

CHECKOUT_EVENT = json.dumps({
    'id': 'evt_test',
    'type': 'checkout.session.completed',
    'data': {'object': {
        'id': 'cs_test', 'customer_email': 'a@example.com', 'amount_total': 5500,
        'currency': 'usd', 'mode': 'subscription', 'metadata': {'telegram_id': '12345'},
    }},
}).encode()

PAYPAL_EVENT = json.dumps({
    'event_type': 'PAYMENT.SALE.COMPLETED',
    'resource': {'custom_id': '12345', 'id': 'PAY-1', 'amount': {'total': '50.00', 'currency': 'USD'}},
}).encode()


def stripe_header(payload, secret=TEST_SECRET, ts=None, extra_sigs=()):
    ts = int(time.time()) if ts is None else ts
    sig = hmac.new(secret.encode(), f'{ts}.'.encode() + payload, hashlib.sha256).hexdigest()
    parts = [f't={ts}'] + [f'v1={s}' for s in extra_sigs] + [f'v1={sig}']
    return ','.join(parts)


def call_app(path, payload=b'', headers=None, method='POST'):
    environ = {'REQUEST_METHOD': method, 'PATH_INFO': path,
               'CONTENT_LENGTH': str(len(payload)), 'wsgi.input': BytesIO(payload)}
    for k, v in (headers or {}).items():
        environ['HTTP_' + k.upper().replace('-', '_')] = v
    result = {}

    def start_response(status, hdrs):
        result['status'] = int(status.split()[0])

    body = b''.join(wh.app(environ, start_response))
    return result['status'], json.loads(body)


class SideEffectsMixin:
    """Patch every function that grants access or touches DB/Telegram."""

    def setUp(self):
        self.mocks = {}
        for name in ('add_subscriber', 'record_payment', 'create_invite_link',
                     'send_dm', 'update_expiry', 'get_db'):
            p = mock.patch.object(wh, name)
            self.mocks[name] = p.start()
            self.addCleanup(p.stop)
        self.mocks['create_invite_link'].return_value = 'https://t.me/+test'

    def assert_no_access_granted(self):
        for name in ('add_subscriber', 'record_payment', 'create_invite_link', 'send_dm'):
            self.mocks[name].assert_not_called()


class StripeWebhookTests(SideEffectsMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {'STRIPE_WEBHOOK_SECRET': TEST_SECRET})
        env.start()
        self.addCleanup(env.stop)

    def test_forged_event_without_header_rejected(self):
        status, _ = call_app('/webhook/stripe', CHECKOUT_EVENT)
        self.assertEqual(status, 400)
        self.assert_no_access_granted()

    def test_bad_signature_rejected(self):
        hdr = stripe_header(CHECKOUT_EVENT, secret='whsec_wrong')
        status, _ = call_app('/webhook/stripe', CHECKOUT_EVENT, {'Stripe-Signature': hdr})
        self.assertEqual(status, 400)
        self.assert_no_access_granted()

    def test_tampered_payload_rejected(self):
        hdr = stripe_header(CHECKOUT_EVENT)
        tampered = CHECKOUT_EVENT.replace(b'5500', b'175000')
        status, _ = call_app('/webhook/stripe', tampered, {'Stripe-Signature': hdr})
        self.assertEqual(status, 400)
        self.assert_no_access_granted()

    def test_stale_timestamp_rejected(self):
        hdr = stripe_header(CHECKOUT_EVENT, ts=int(time.time()) - 301)
        status, _ = call_app('/webhook/stripe', CHECKOUT_EVENT, {'Stripe-Signature': hdr})
        self.assertEqual(status, 400)
        self.assert_no_access_granted()

    def test_malformed_header_rejected(self):
        for hdr in ('garbage', 't=notanint,v1=abc', f't={int(time.time())}', 'v1=abc'):
            status, _ = call_app('/webhook/stripe', CHECKOUT_EVENT, {'Stripe-Signature': hdr})
            self.assertEqual(status, 400, hdr)
        self.assert_no_access_granted()

    def test_valid_signature_accepted(self):
        hdr = stripe_header(CHECKOUT_EVENT)
        status, body = call_app('/webhook/stripe', CHECKOUT_EVENT, {'Stripe-Signature': hdr})
        self.assertEqual((status, body), (200, {'ok': True}))
        self.mocks['add_subscriber'].assert_called_once()
        self.mocks['send_dm'].assert_called_once()

    def test_multiple_v1_signatures_any_match_accepted(self):
        hdr = stripe_header(CHECKOUT_EVENT, extra_sigs=('0' * 64,))
        status, _ = call_app('/webhook/stripe', CHECKOUT_EVENT, {'Stripe-Signature': hdr})
        self.assertEqual(status, 200)

    def test_missing_secret_refused(self):
        with mock.patch.dict(os.environ, {'STRIPE_WEBHOOK_SECRET': ''}):
            hdr = stripe_header(CHECKOUT_EVENT)
            status, _ = call_app('/webhook/stripe', CHECKOUT_EVENT, {'Stripe-Signature': hdr})
        self.assertEqual(status, 503)
        self.assert_no_access_granted()


class VerifyStripeSignatureUnitTests(unittest.TestCase):
    def test_tolerance_boundaries(self):
        ts = 1_700_000_000
        hdr = stripe_header(b'{}', ts=ts)
        self.assertTrue(wh.verify_stripe_signature(b'{}', hdr, TEST_SECRET, now=ts + 300))
        self.assertFalse(wh.verify_stripe_signature(b'{}', hdr, TEST_SECRET, now=ts + 301))
        self.assertFalse(wh.verify_stripe_signature(b'{}', hdr, TEST_SECRET, now=ts - 301))

    def test_empty_secret_never_verifies(self):
        self.assertFalse(wh.verify_stripe_signature(b'{}', stripe_header(b'{}', secret=''), ''))


PAYPAL_HEADERS = {
    'PayPal-Auth-Algo': 'SHA256withRSA', 'PayPal-Cert-Url': 'https://api.paypal.com/cert',
    'PayPal-Transmission-Id': 'tid', 'PayPal-Transmission-Sig': 'sig',
    'PayPal-Transmission-Time': '2026-01-01T00:00:00Z',
}
PAYPAL_ENV = {'PAYPAL_CLIENT_ID': 'cid', 'PAYPAL_CLIENT_SECRET': 'csecret',
              'PAYPAL_WEBHOOK_ID': 'WH-1', 'PAYPAL_API_BASE': 'https://paypal.invalid'}


def fake_paypal_http(verification_status):
    http = mock.Mock()

    def post(url, **kw):
        resp = mock.Mock()
        if url.endswith('/v1/oauth2/token'):
            resp.json.return_value = {'access_token': 'tok'}
        else:
            resp.json.return_value = {'verification_status': verification_status}
        return resp

    http.post.side_effect = post
    return http


class PayPalWebhookTests(SideEffectsMixin, unittest.TestCase):
    def test_unconfigured_refuses_and_grants_nothing(self):
        http = fake_paypal_http('SUCCESS')
        with mock.patch.dict(os.environ, {k: '' for k in PAYPAL_ENV}), \
             mock.patch.object(wh, 'requests', http):
            status, _ = call_app('/webhook/paypal', PAYPAL_EVENT, PAYPAL_HEADERS)
        self.assertEqual(status, 400)
        http.post.assert_not_called()
        self.assert_no_access_granted()

    def test_verification_failure_grants_nothing(self):
        with mock.patch.dict(os.environ, PAYPAL_ENV), \
             mock.patch.object(wh, 'requests', fake_paypal_http('FAILURE')):
            status, _ = call_app('/webhook/paypal', PAYPAL_EVENT, PAYPAL_HEADERS)
        self.assertEqual(status, 400)
        self.assert_no_access_granted()

    def test_missing_headers_grants_nothing(self):
        http = fake_paypal_http('SUCCESS')
        with mock.patch.dict(os.environ, PAYPAL_ENV), mock.patch.object(wh, 'requests', http):
            status, _ = call_app('/webhook/paypal', PAYPAL_EVENT, {})
        self.assertEqual(status, 400)
        http.post.assert_not_called()
        self.assert_no_access_granted()

    def test_network_error_grants_nothing(self):
        http = mock.Mock()
        http.post.side_effect = OSError('boom')
        with mock.patch.dict(os.environ, PAYPAL_ENV), mock.patch.object(wh, 'requests', http):
            status, _ = call_app('/webhook/paypal', PAYPAL_EVENT, PAYPAL_HEADERS)
        self.assertEqual(status, 400)
        self.assert_no_access_granted()

    def test_verified_event_processed(self):
        http = fake_paypal_http('SUCCESS')
        with mock.patch.dict(os.environ, PAYPAL_ENV), mock.patch.object(wh, 'requests', http):
            status, _ = call_app('/webhook/paypal', PAYPAL_EVENT, PAYPAL_HEADERS)
        self.assertEqual(status, 200)
        self.mocks['add_subscriber'].assert_called_once()
        verify_call = http.post.call_args_list[-1]
        self.assertTrue(verify_call.args[0].endswith('/v1/notifications/verify-webhook-signature'))
        self.assertEqual(verify_call.kwargs['json']['webhook_id'], 'WH-1')


class AppAndConfigTests(unittest.TestCase):
    def test_health(self):
        self.assertEqual(call_app('/health', method='GET'), (200, {'status': 'ok'}))

    def test_unknown_path(self):
        self.assertEqual(call_app('/nope', method='GET')[0], 404)

    def test_missing_token_gives_clear_error_lazily(self):
        with mock.patch.dict(os.environ, {'POLYSHARK_BOT_TOKEN': '',
                                          'POLYSHARK_TOKEN_FILE': '/nonexistent/token'}), \
             mock.patch.object(wh, '_token_cache', None):
            with self.assertRaises(wh.ConfigError):
                wh.get_bot_token()

    def test_check_config_requires_stripe_secret(self):
        with mock.patch.dict(os.environ, {'STRIPE_WEBHOOK_SECRET': ''}):
            with self.assertRaises(wh.ConfigError):
                wh.check_config()


if __name__ == '__main__':
    unittest.main()
