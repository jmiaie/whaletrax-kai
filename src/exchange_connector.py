#!/usr/bin/env python3
"""
Polyshark Exchange Connector v2 — crypto price feeds.
No API keys needed. Works around US geo-restrictions.

Tested sources (2026-04-25):
  ✅ CoinGecko  — free, no auth, works from US VPS
  ✅ Coinbase   — public spot price works
  ✅ KuCoin     — public ticker works (no KYC needed)
  ✅ OKX        — public ticker works
  🔴 Binance    — BLOCKED (451 Legal) for US IPs
  🔴 Bybit      — requires API key even for public
  🔴 Bitstamp  — EU only
"""

import requests, time, json
from datetime import datetime

SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; PolysharkBot/1.0)'})

def kucoin_ticker(pair='BTC-USDT') -> dict:
    """KuCoin public ticker — works from US."""
    try:
        url = f'https://api.kucoin.com/api/v1/market/orderbook/level1'
        params = {'symbol': pair}
        r = SESSION.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get('data'):
            ticker = data['data']
            return {
                'exchange': 'kucoin',
                'bid': float(ticker.get('bestBid', 0)),
                'ask': float(ticker.get('bestAsk', 0)),
                'price': float(ticker.get('price', 0)),
                'size': float(ticker.get('size', 0)),
                'ts': int(ticker.get('time', 0)) // 1_000_000,  # µs → s
            }
    except Exception as e:
        print(f"KuCoin error: {e}")
    return {}

def okx_ticker(instId='BTC-USDT') -> dict:
    """OKX public ticker — works from US."""
    try:
        url = 'https://www.okx.com/api/v5/market/ticker'
        params = {'instId': instId}
        r = SESSION.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get('data'):
            t = data['data'][0]
            return {
                'exchange': 'okx',
                'bid': float(t.get('bidPx', 0)),
                'ask': float(t.get('askPx', 0)),
                'price': float(t.get('last', 0)),
                'size': float(t.get('vol24h', 0)),
                'ts': int(t.get('ts', 0)) // 1_000,
            }
    except Exception as e:
        print(f"OKX error: {e}")
    return {}

def coingecko_price(coin='bitcoin', vs='usd') -> dict:
    """CoinGecko free tier — works from US."""
    try:
        url = f'https://api.coingecko.com/api/v3/simple/price'
        params = {'ids': coin, 'vs_currencies': vs,
                  'include_24hr_change': 'true', 'include_24hr_vol': 'true'}
        r = SESSION.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
        if coin in data:
            return {
                'exchange': 'coingecko',
                'price': data[coin].get('usd', 0),
                'change_24h': data[coin].get('usd_24h_change', 0),
                'volume_24h': data[coin].get('usd_24h_vol', 0),
            }
    except Exception as e:
        print(f"CoinGecko error: {e}")
    return {}

def coingecko_ohlc(coin='bitcoin', days=7) -> list:
    """CoinGecko OHLC — 7 day chart for Kronos."""
    try:
        url = f'https://api.coingecko.com/api/v3/coins/{coin}/ohlc'
        params = {'vs_currency': 'usd', 'days': days}
        r = SESSION.get(url, params=params, timeout=15)
        r.raise_for_status()
        # Returns: [timestamp, open, high, low, close]
        return r.json()
    except Exception as e:
        print(f"CoinGecko OHLC error: {e}")
        return []

def coinbase_spot(quote_currency='BTC', base='USD') -> float:
    """Coinbase public spot price."""
    try:
        url = f'https://api.coinbase.com/v2/prices/{base}-{quote_currency}/spot'
        r = SESSION.get(url, timeout=10)
        r.raise_for_status()
        return float(r.json()['data']['amount'])
    except Exception as e:
        print(f"Coinbase spot error: {e}")
        return 0.0

# ── Consensus BTC Price ────────────────────────────────────────────────────────

def get_btc_price() -> dict:
    """Get BTC/USD from multiple sources. Returns consensus."""
    result = {}
    
    # KuCoin
    kk = kucoin_ticker('BTC-USDT')
    if kk.get('price'):
        result['kucoin'] = kk['price']
    
    # OKX
    okx = okx_ticker('BTC-USDT')
    if okx.get('price'):
        result['okx'] = okx['price']
    
    # CoinGecko
    cg = coingecko_price('bitcoin', 'usd')
    if cg.get('price'):
        result['coingecko'] = cg['price']
    
    # Coinbase
    cb = coinbase_spot('BTC', 'USD')
    if cb > 0:
        result['coinbase'] = cb
    
    prices = [v for v in result.values() if v > 0]
    consensus = sum(prices) / len(prices) if prices else 0
    
    return {
        'sources': result,
        'consensus': round(consensus, 2),
        'ts': int(time.time()),
    }

# ── Kronos OHLCV Adapter ──────────────────────────────────────────────────────

def get_kronos_ohlcv(coin='bitcoin', days=7) -> list[list]:
    """
    Get OHLCV data in Kronos format [timestamp, O, H, L, C, V].
    Uses CoinGecko (no auth required, works from US VPS).
    
    days: 1|7|14|30|90|180|365|max
    """
    raw = coingecko_ohlc(coin, days)
    
    kronos = []
    for k in raw:
        ts = int(k[0] // 1000)  # ms → s
        kronos.append([ts, k[1], k[2], k[3], k[4], k[4]])  # volume = close as proxy
    
    return kronos

# ── Demo ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("🪙 POLYSHARK EXCHANGE CONNECTOR v2")
    print("=" * 50)
    
    # BTC consensus price
    btc = get_btc_price()
    print(f"\nBTC/USD ({btc['ts']}):")
    for src, price in btc['sources'].items():
        print(f"  {src:12s}: ${price:>10,.2f}")
    print(f"  {'CONSENSUS':12s}: ${btc['consensus']:>10,.2f}")
    
    # Kronos format OHLCV (7 days)
    print("\n📊 Kronos OHLCV — BTC/USD (7 day, 7 candles):")
    kronos = get_kronos_ohlcv('bitcoin', 7)
    for k in kronos[-7:]:
        ts = datetime.utcfromtimestamp(k[0]).strftime('%m-%d %H:%M')
        print(f"  [{ts}] O:{k[1]:,.0f} H:{k[2]:,.0f} L:{k[3]:,.0f} C:{k[4]:,.0f}")
