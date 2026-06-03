#!/usr/bin/env python3
"""
Polyshark Alert Card Generator v1.2
Jeff Milam spec — 2026-04-25

Three card types:
  generate_card()       — WIN alerts (green / profit)
  generate_loss_card() — LOSS alerts (red / loss)
  generate_free_teaser() — Free tier (stripped text)

Plus one unified wrapper used by live_entry_tracker.py / Kai:
  make_trade_alert_card() — auto-selects WIN/LOSS card based on P&L sign
"""

from PIL import Image, ImageDraw, ImageFont

def _sport_emoji(q: str) -> str:
    q = q.lower()
    if any(k in q for k in ['mets','yankees','dodgers','athletics','rangers','red sox','cubs','sox','mariners','padres','rockies','brewers','phillies','marlins','diamondbacks','giants','nationals','orioles','astros','guardians','twins','tigers','reds']): return '⚾'
    if any(k in q for k in ['lakers','celtics','warriors','nba','basketball','knicks','hawks','spurs','bulls','heat','suns','bucks','76ers']): return '🏀'
    if any(k in q for k in ['nfl','football','cowboys','eagles','chiefs','packers','bills','patriots']): return '🏈'
    if any(k in q for k in ['hockey','bruins','flyers','penguins','devils','avalanche','golden knights','kraken','jets']): return '🏒'
    if any(k in q for k in ['ufc','mma','spann','griffin','suarez','barcelos','godinez']): return '🥊'
    if any(k in q for k in ['tennis','wimbledon','us open','madrid open','australian open']): return '🎾'
    if any(k in q for k in ['golf','masters','pga','tiger woods']): return '⛳'
    if any(k in q for k in ['soccer','fc','real madrid','barcelona','manchester','liverpool','chelsea','arsenal','leicester',' IPL','cricket','delhi capitals','sunrisers']): return '⚽'
    if any(k in q for k in ['ipl','cricket','sunrisers hyderabad','lucknow super giants','mumbai indians']): return '🏏'
    return ''


def _abbrev_wallet(wallet: str) -> str:
    wallet = wallet.strip()
    if len(wallet) <= 12:
        return wallet
    return f"{wallet[:8]}...{wallet[-6:]}"


def _wrap_text(draw, text, font, max_width):
    words = text.split()
    lines, line = [], []
    for w in words:
        test = ' '.join(line + [w])
        if draw.textlength(test, font=font) <= max_width:
            line.append(w)
        else:
            if line:
                lines.append(' '.join(line))
                line = [w]
            else:
                lines.append(w)
    if line:
        lines.append(' '.join(line))
    return lines


def _wallet_link_text(wallet: str) -> str:
    return _abbrev_wallet(wallet)


def _potential_roi_usd(size_usdc: float, roi_pct: float) -> float:
    return round(size_usdc * abs(roi_pct) / 100, 2)


def _format_wallet_line(wallet: str, confidence: str, roi_30d: float = 0.0, lifetime_roi: float = 0.0, lifetime_wr: float = 0.0, trades_n: int = 0, win_rate_30d: float = 0.0) -> str:
    abbrev = _abbrev_wallet(wallet)
    extras = []
    if win_rate_30d > 0 or roi_30d != 0:
        extras.append(f"30D WR: {win_rate_30d:.0f}% | ROI: {roi_30d:+.1f}%")
    if lifetime_roi != 0:
        extras.append(f"Lifetime ROI: {lifetime_roi:+.1f}%")
    if lifetime_wr != 0:
        extras.append(f"Lifetime WR: {lifetime_wr:.0f}%")
    if trades_n > 0:
        extras.append(f"Trades: {trades_n}")
    extra_text = ' | '.join(extras)
    tail = f" | {extra_text}" if extra_text else ''
    return f"🐋 {abbrev} | [Confidence: {confidence}]{tail}"


def _trade_summary_line(side: str, price: float, size_usdc: float, roi_pct: float = 0.0, roi_usd: float = 0.0) -> str:
    side_label = side.upper()
    roi_part = f" | Potential ROI: {roi_pct:+.1f}%" if roi_pct else ''
    usd_part = f" | ${roi_usd:,.0f}" if roi_usd else ''
    return f"💵 BET: {side_label} on - | Entry: ${price:.2f} | Position: ${size_usdc:,.0f}{roi_part}{usd_part}"
import os
from datetime import datetime
import math

# ── Fonts ────────────────────────────────────────────────────────────────────
def get_font(size, bold=False):
    bold_paths = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
    ]
    reg_paths = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
    ]
    paths = bold_paths if bold else reg_paths
    for p in paths:
        if os.path.exists(p):
            try: return ImageFont.truetype(p, size)
            except: pass
    return ImageFont.load_default()

# ── Colors ────────────────────────────────────────────────────────────────────
BG       = (10,  12,  28)
CARD_BG  = (14,  18,  40)
GREEN    = (0,  220, 140)
RED      = (255,  68,  68)
GOLD     = (255, 180,  40)
TEAL     = (0,  210, 180)
WHITE    = (240, 242, 250)
MUTED    = (110, 130, 170)
DIVIDER  = (28,  34,  62)
AMBER    = (255, 170,  40)
WIDTH    = 780
PAD      = 30

def divider(draw, y):
    draw.rectangle([PAD, y, WIDTH - PAD, y + 1], fill=DIVIDER)

def fmt_ts(ts, include_time=False):
    if not ts: return 'LIVE'
    try:
        # If ts is a string like "2025-11-15T00:00:00Z", parse it
        if isinstance(ts, str):
            if 'T' in ts:
                ts = ts.split('T')[0]
            return ts
        
        dt = datetime.fromtimestamp(ts, tz=None)
        if include_time:
            return dt.strftime('%Y-%m-%d, %H:%M UTC')
        return dt.strftime('%Y-%m-%d')
    except:
        return 'LIVE'

# ── Badge helpers ─────────────────────────────────────────────────────────────
def wr_badge(wr):
    if wr >= 65: return (GREEN, f'🏆 🟢 {wr:.0f}% lifetime WR')
    if wr >= 45: return (AMBER, f'🏆 🟠 {wr:.0f}% lifetime WR')
    if wr > 0:   return (RED,   f'🏆 🔴 {wr:.0f}% lifetime WR')
    return None, None

def streak_badge(streak):
    if not streak or streak < 2: return None
    if streak >= 8: return (GOLD,  f'🔥🔥 ON FIRE 🔥🔥')
    if streak >= 5: return (AMBER, f'🔥 {streak}-win streak')
    return (AMBER, f'🔥 {streak}-win streak')

# ─────────────────────────────────────────────────────────────────────────────
#  WIN CARD
# ─────────────────────────────────────────────────────────────────────────────
def generate_card(
    market_question: str,
    direction: str,          # 'UP' or 'DOWN'
    profit: float,           # signed profit (positive = win)
    roi: float,              # Lifetime ROI % (signed)
    size_usdc: float,
    masked_wallet: str,      # e.g. '0x....abcd'
    lifetime_wr: float = 0,
    trades_n: int = 0,
    current_streak: int = 0,
    ts_opened: int = 0,
    ts_closes: int = 0,
    ts_resolved: int = 0,
    market_url: str = '',
    whale_badge: bool = False,
    confidence: str = 'HIGH',
    lifetime_roi: float = 0.0,   # Lifetime ROI % (e.g. 67.5)
    roi_30d: float = 0.0,        # 30-day ROI % (e.g. 42.1)
    win_rate_30d: float = 0.0,   # 30-day win rate % (e.g. 72.0)
    confidence_score: int = 0,   # 0-100 score
    is_open: bool = True,           # True=ENTRY, False=WIN
    geo_available: str = 'UNKNOWN',  # 'GLOBAL' / 'NON_US_ONLY' / 'UNKNOWN'
    img_path: str = '/tmp/polyshark_card.png',
) -> str:
    height = 510
    if whale_badge: height += 44
    if current_streak >= 5: height += 40
    if lifetime_roi != 0: height += 38
    if win_rate_30d > 0 or roi_30d != 0: height += 38

    img  = Image.new('RGB', (WIDTH, height), color=BG)
    draw = ImageDraw.Draw(img)
    f32  = get_font(32, bold=True)
    f24  = get_font(24, bold=True)
    f20b = get_font(20, bold=True)
    f18  = get_font(18)
    f16  = get_font(16)
    f14  = get_font(14)

    # ── HEADER ──────────────────────────────────────────────────────────────
    draw.rectangle([0, 0, WIDTH, 58], fill=CARD_BG)
    # WIN vs ENTRY based on market status
    from datetime import datetime, timezone as tz
    is_open_card = True
    try:
        if ts_resolved > 0:
            is_open_card = datetime.now(tz.utc) < datetime.fromtimestamp(ts_resolved, tz=tz.utc)
    except: pass
    # Add sport emoji to question
    sq = _sport_emoji(market_question)
    sq_label = f'{sq} {market_question}' if sq else market_question

    draw.text((PAD, 16), 'POLYSHARK', font=get_font(20, bold=True), fill=TEAL)
    draw.text((PAD + 172, 18), 'WHALE TRACKER', font=f14, fill=MUTED)

    conf_color = GREEN if confidence == 'HIGH' else GOLD
    conf_label = f'● {confidence} CONFIDENCE'
    cw = draw.textlength(conf_label, font=f20b)
    draw.rounded_rectangle([WIDTH - PAD - cw - 14, 12, WIDTH - PAD, 44], radius=7, fill=(20, 24, 52))
    draw.text((WIDTH - PAD - cw - 7, 15), conf_label, font=f20b, fill=conf_color)

    # ── WHALE BADGE ─────────────────────────────────────────────────────────
    y = 62 if whale_badge else 68
    if whale_badge:
        wb  = '🏅 HIGH-FREQ WINNING WHALE 🏅'
        ww  = draw.textlength(wb, font=f20b)
        draw.rounded_rectangle([PAD, 62, PAD + ww + 20, 62 + 34], radius=7, fill=(30, 22, 5))
        draw.text((PAD + 10, 62 + 6), wb, font=f20b, fill=GOLD)
        y = 108

    # ── DIRECTION + QUESTION ────────────────────────────────────────────────
    arrow     = '⬆️' if direction.upper() == 'UP' else '⬇️'
    dir_label = f'{arrow} BET {direction.upper()} on '
    draw.text((PAD, y), dir_label, font=f24, fill=WHITE)
    dw     = draw.textlength(dir_label, font=f24)
    q_font = get_font(24, bold=True)
    max_qw = WIDTH - PAD - dw - 10
    words  = sq_label.split()  # with sport emoji
    lines, line = [], []
    for w in words:
        test = ' '.join(line + [w])
        if draw.textlength(test, font=q_font) <= max_qw:
            line.append(w)
        else:
            if line: lines.append(' '.join(line)); line = [w]
            else:   lines.append(w)
    if line: lines.append(' '.join(line))
    draw.text((PAD + dw, y), lines[0], font=q_font, fill=WHITE)
    if len(lines) > 1:
        y += 32
        draw.text((PAD, y), lines[1], font=q_font, fill=WHITE)
    y += 40

    # ── STATS ROW ───────────────────────────────────────────────────────────
    divider(draw, y); y += 14

    draw.text((PAD, y), f'💰 ${profit:,.0f} | {"💲" if roi < 0 else "✅"} {roi:+.0f}% ROI', font=f24, fill=GREEN if profit >= 0 else RED)

    size_str = f'💵 Size: ${size_usdc:,.0f}' if size_usdc < 1_000_000 else f'💵 Size: ${size_usdc/1_000_000:.1f}M'
    sw = draw.textlength(size_str, font=f24)
    draw.text((WIDTH - PAD - sw, y), size_str, font=f24, fill=WHITE)
    y += 44

    potential_roi_pct = roi_30d if roi_30d != 0 else (roi if abs(roi) <= 100 else 0.0)
    potential_roi_usd = _potential_roi_usd(size_usdc, potential_roi_pct)
    entry_label = f'📊 Entry: ${profit if profit > 0 else 0.00:.2f} | Potential ROI: {potential_roi_pct:+.1f}% | ${potential_roi_usd:,.0f}'
    draw.text((PAD, y), entry_label, font=f16, fill=MUTED)
    y += 30

    # ── WIN RATE + LIFETIME ─────────────────────────────────────────────────
    divider(draw, y); y += 14
    wr_col, wr_lbl = wr_badge(lifetime_wr)
    if wr_lbl:
        draw.text((PAD, y), wr_lbl, font=f20b, fill=wr_col)
        draw.text((PAD + 145, y), 'LIFETIME', font=f16, fill=MUTED)
        if lifetime_roi != 0:
            roi_col_l = GREEN if lifetime_roi >= 0 else RED
            roi_sign = '+' if lifetime_roi >= 0 else ''
            roi_label_l = 'potential ROI' if is_open else 'ROI'
            draw.text((PAD + 220, y), f'{roi_sign}{lifetime_roi:.1f}% {roi_label_l}', font=f20b, fill=roi_col_l)
    if trades_n > 0:
        n_str = f'  n={trades_n}'
        draw.text((PAD + 400, y), n_str, font=f16, fill=MUTED)
    y += 34

    # ── 30d Win Rate + 30d ROI ─────────────────────────────────────────
    if win_rate_30d > 0 or roi_30d != 0:
        divider(draw, y); y += 14
        roi_col_30 = GREEN if roi_30d >= 0 else RED
        roi_sign_30 = '+' if roi_30d >= 0 else ''
        wr30_val = win_rate_30d or 0
        if wr30_val > 0:
            wr30_badge_col = GREEN if wr30_val >= 65 else (AMBER if wr30_val >= 45 else RED)
            draw.text((PAD, y), f'🏆 {wr30_val:.0f}% WR', font=f20b, fill=wr30_badge_col)
            draw.text((PAD + 145, y), '30D', font=f16, fill=MUTED)
            roi_label_30 = 'potential ROI' if is_open else 'ROI'
            draw.text((PAD + 190, y), f'{roi_sign_30}{roi_30d:.1f}% {roi_label_30}', font=f20b, fill=roi_col_30)
        else:
            roi_label_30 = 'potential ROI' if is_open else 'ROI'
            draw.text((PAD, y), f'🏆 30D WR | {roi_sign_30}{roi_30d:.1f}% {roi_label_30}', font=f20b, fill=roi_col_30)
        y += 34

    # ── STREAK ─────────────────────────────────────────────────────────────
    st_b = streak_badge(current_streak)
    if st_b:
        st_col, st_lbl = st_b
        divider(draw, y); y += 14
        draw.text((PAD, y), st_lbl, font=f20b, fill=st_col)
        y += 38

    # ── DATES ──────────────────────────────────────────────────────────────
    divider(draw, y); y += 14
    parts = []
    if ts_opened:
        parts.append(f'O: {fmt_ts(ts_opened, include_time=True)}')
    if ts_closes:
        label = 'Closes' if is_open else 'Closed'
        parts.append(f'{label}: {fmt_ts(ts_closes)}')
    if ts_resolved:
        parts.append(f'C: {fmt_ts(ts_resolved)}')
    if parts:
        draw.text((PAD, y), '  |  '.join(parts), font=f16, fill=MUTED)
        y += 30
    else:
        draw.text((PAD, y), 'O: —', font=f16, fill=MUTED)
        y += 30

    # ── LINKS ───────────────────────────────────────────────────────────────
    # URLs omitted — Polymarket restricts crypto/specialty markets globally
    wallet_line = _format_wallet_line(masked_wallet, confidence, roi_30d=roi_30d, lifetime_roi=lifetime_roi, lifetime_wr=lifetime_wr, trades_n=trades_n, win_rate_30d=win_rate_30d)
    draw.text((PAD, y), wallet_line, font=f16, fill=TEAL)

    y += 30

    # ── FOOTER ──────────────────────────────────────────────────────────────
    footer_y = y + 28
    draw.text((PAD, footer_y + 4), 'Polyshark · Whaletrax', font=f14, fill=(50, 55, 80))
    draw.text((WIDTH - PAD - 180, footer_y + 4), '🔒 Identity anonymized 🌊', font=f14, fill=(50, 55, 80))

    # ── GEO RESTRICTION BADGE ───────────────────────────────────────────
    if geo_available == 'NON_US_ONLY':
        geo_lbl = '🇺🇸 US Only'
        geo_col = (50, 130, 255)  # RED
        draw.text((PAD + 200, footer_y + 4), geo_lbl, font=f14, fill=geo_col)
    elif geo_available == 'GLOBAL':
        geo_lbl = '🌍 Global'
        geo_col = (50, 180, 100)  # GREEN
        draw.text((PAD + 200, footer_y + 4), geo_lbl, font=f14, fill=geo_col)
    # UNKNOWN = silent (no badge)

    img.save(img_path, 'PNG')
    print(f'Card saved → {img_path}')
    return img_path


# ─────────────────────────────────────────────────────────────────────────────
#  LOSS CARD
# ─────────────────────────────────────────────────────────────────────────────
def generate_loss_card(
    market_question: str,
    direction: str,           # 'UP' or 'DOWN'
    loss: float,             # negative number (e.g. -420)
    roi: float,              # negative ROI %
    size_usdc: float,
    masked_wallet: str,
    lifetime_wr: float = 0,
    trades_n: int = 0,
    current_streak: int = 0,
    ts_opened: int = 0,
    ts_closes: int = 0,
    ts_resolved: int = 0,
    market_url: str = '',
    confidence: str = 'MEDIUM',
    lifetime_roi: float = 0.0,
    roi_30d: float = 0.0,
    win_rate_30d: float = 0.0,   # 30-day win rate % (e.g. 72.0)
    is_open: bool = True,
    geo_available: str = 'UNKNOWN',  # 'GLOBAL' / 'NON_US_ONLY' / 'UNKNOWN'
    img_path: str = '/tmp/polyshark_loss_card.png',
) -> str:
    height = 510
    if current_streak >= 5: height += 40
    if lifetime_roi != 0: height += 38
    if win_rate_30d > 0 or roi_30d != 0: height += 38

    img  = Image.new('RGB', (WIDTH, height), color=BG)
    draw = ImageDraw.Draw(img)
    f32  = get_font(32, bold=True)
    f24  = get_font(24, bold=True)
    f20b = get_font(20, bold=True)
    f16  = get_font(16)
    f14  = get_font(14)

    # ── HEADER (red accent) ─────────────────────────────────────────────────
    draw.rectangle([0, 0, WIDTH, 58], fill=(30, 14, 14))
    # WIN vs ENTRY based on market status
    from datetime import datetime, timezone as tz
    is_open_card = True
    try:
        if ts_resolved > 0:
            is_open_card = datetime.now(tz.utc) < datetime.fromtimestamp(ts_resolved, tz=tz.utc)
    except: pass

    draw.text((PAD, 16), 'POLYSHARK', font=get_font(20, bold=True), fill=RED)
    draw.text((PAD + 172, 18), 'WHALE TRACKER', font=f14, fill=MUTED)

    conf_label = f'● {confidence} CONFIDENCE'
    cw = draw.textlength(conf_label, font=f20b)
    draw.rounded_rectangle([WIDTH - PAD - cw - 14, 12, WIDTH - PAD, 44], radius=7, fill=(40, 14, 14))
    draw.text((WIDTH - PAD - cw - 7, 15), conf_label, font=f20b, fill=RED)

    # ── DIRECTION + QUESTION ────────────────────────────────────────────────
    y = 68
    sq      = _sport_emoji(market_question)
    sq_label = f'{sq} {market_question}' if sq else market_question
    arrow     = '⬆️' if direction.upper() == 'UP' else '⬇️'
    dir_label = f'{arrow} BET {direction.upper()} on '
    draw.text((PAD, y), dir_label, font=f24, fill=WHITE)
    dw     = draw.textlength(dir_label, font=f24)
    q_font = get_font(24, bold=True)
    max_qw = WIDTH - PAD - dw - 10
    words  = sq_label.split()  # with sport emoji
    lines, line = [], []
    for w in words:
        test = ' '.join(line + [w])
        if draw.textlength(test, font=q_font) <= max_qw:
            line.append(w)
        else:
            if line: lines.append(' '.join(line)); line = [w]
            else:   lines.append(w)
    if line: lines.append(' '.join(line))
    draw.text((PAD + dw, y), lines[0], font=q_font, fill=WHITE)
    if len(lines) > 1:
        y += 32
        draw.text((PAD, y), lines[1], font=q_font, fill=WHITE)
    y += 40

    # ── STATS ROW ───────────────────────────────────────────────────────────
    divider(draw, y); y += 14

    draw.text((PAD, y), f'🚫 {loss:+,.0f}$', font=f32, fill=RED)

    roi_str = f'💲 {roi:.2f}% ROI'
    draw.text((PAD + 250, y + 6), roi_str, font=f24, fill=RED)

    size_str = f'💳 ${size_usdc:,.0f}' if size_usdc < 1_000_000 else f'💳 ${size_usdc/1_000_000:.1f}M'
    sw = draw.textlength(size_str, font=f24)
    draw.text((WIDTH - PAD - sw, y), size_str, font=f24, fill=WHITE)
    y += 44

    # ── WIN RATE + LIFETIME ROI ───────────────────────────────────────────
    divider(draw, y); y += 14
    wr_col, wr_lbl = wr_badge(lifetime_wr)
    if wr_lbl: draw.text((PAD, y), wr_lbl, font=f20b, fill=wr_col)
    if trades_n > 0:
        draw.text((PAD + 280, y), f'  n={trades_n}', font=f20b, fill=MUTED)
    if lifetime_roi != 0:
        roi_col_l = GREEN if lifetime_roi >= 0 else RED
        roi_sign = '+' if lifetime_roi >= 0 else ''
        roi_lbl_l = f'{roi_sign}{lifetime_roi:.1f}% lifetime ROI'
        draw.text((PAD + 380, y), roi_lbl_l, font=f20b, fill=roi_col_l)
    y += 36

    # ── 30d Win Rate + 30d ROI ─────────────────────────────────────────
    if win_rate_30d > 0 or roi_30d != 0:
        divider(draw, y); y += 14
        roi_col_30 = GREEN if roi_30d >= 0 else RED
        roi_sign_30 = '+' if roi_30d >= 0 else ''
        wr30_val = win_rate_30d or 0
        if wr30_val > 0:
            wr30_badge_col = GREEN if wr30_val >= 65 else (AMBER if wr30_val >= 45 else RED)
            draw.text((PAD, y), f'🏆 {wr30_val:.0f}% WR', font=f20b, fill=wr30_badge_col)
            draw.text((PAD + 145, y), '30D', font=f16, fill=MUTED)
            roi_label_30 = 'potential ROI' if is_open else 'ROI'
            draw.text((PAD + 190, y), f'{roi_sign_30}{roi_30d:.1f}% {roi_label_30}', font=f20b, fill=roi_col_30)
        else:
            roi_label_30 = 'potential ROI' if is_open else 'ROI'
            draw.text((PAD, y), f'🏆 30D WR | {roi_sign_30}{roi_30d:.1f}% {roi_label_30}', font=f20b, fill=roi_col_30)
        y += 34

    # ── STREAK ─────────────────────────────────────────────────────────────
    st_b = streak_badge(current_streak)
    if st_b:
        st_col, st_lbl = st_b
        divider(draw, y); y += 14
        draw.text((PAD, y), st_lbl, font=f20b, fill=st_col)
        y += 38

    # ── DATES ──────────────────────────────────────────────────────────────
    divider(draw, y); y += 14
    parts = []
    if ts_opened:
        parts.append(f'O: {fmt_ts(ts_opened, include_time=True)}')
    if ts_closes:
        label = 'Closes' if is_open else 'Closed'
        parts.append(f'{label}: {fmt_ts(ts_closes)}')
    if ts_resolved:
        parts.append(f'C: {fmt_ts(ts_resolved)}')
    if parts:
        draw.text((PAD, y), '  |  '.join(parts), font=f16, fill=MUTED)
        y += 30
    else:
        draw.text((PAD, y), 'O: —', font=f16, fill=MUTED)
        y += 30

    # ── LINKS ───────────────────────────────────────────────────────────────
    # URLs omitted — Polymarket restricts crypto/specialty markets globally
    wallet_line = _format_wallet_line(masked_wallet, confidence, roi_30d=roi_30d, lifetime_roi=lifetime_roi, lifetime_wr=lifetime_wr, trades_n=trades_n, win_rate_30d=win_rate_30d)
    draw.text((PAD, y), wallet_line, font=f16, fill=TEAL)

    y += 30

    # ── FOOTER ──────────────────────────────────────────────────────────────
    footer_y = y + 28
    draw.text((PAD, footer_y + 4), 'Polyshark · Whaletrax', font=f14, fill=(50, 55, 80))
    draw.text((WIDTH - PAD - 180, footer_y + 4), '🔒 Identity anonymized 🌊', font=f14, fill=(50, 55, 80))

    # ── GEO RESTRICTION BADGE ───────────────────────────────────────────
    if geo_available == 'NON_US_ONLY':
        geo_lbl = '🇺🇸 US Only'
        geo_col = (50, 130, 255)  # RED
        draw.text((PAD + 200, footer_y + 4), geo_lbl, font=f14, fill=geo_col)
    elif geo_available == 'GLOBAL':
        geo_lbl = '🌍 Global'
        geo_col = (50, 180, 100)  # GREEN
        draw.text((PAD + 200, footer_y + 4), geo_lbl, font=f14, fill=geo_col)
    # UNKNOWN = silent (no badge)

    img.save(img_path, 'PNG')
    print(f'Loss card saved → {img_path}')
    return img_path


# ─────────────────────────────────────────────────────────────────────────────
#  FREE TEASER CARD (text-only strip)
# ─────────────────────────────────────────────────────────────────────────────
def generate_free_teaser(
    market_question: str,
    direction: str,         # 'UP' or 'DOWN'
    entry_price: float,
    ts_opened: int = 0,
    ts_resolved: int = 0,
    market_url: str = '',
    geo_available: str = 'UNKNOWN',  # 'GLOBAL' / 'NON_US_ONLY' / 'UNKNOWN'
    img_path: str = '/tmp/polyshark_teaser.png',
) -> str:
    """Stripped card — Play + Direction + Entry + Opened date only."""

    img  = Image.new('RGB', (WIDTH, 340), color=BG)
    draw = ImageDraw.Draw(img)
    f24  = get_font(24, bold=True)
    f20b = get_font(20, bold=True)
    f16  = get_font(16)
    f14  = get_font(14)

    # ── HEADER ──────────────────────────────────────────────────────────────
    draw.rectangle([0, 0, WIDTH, 58], fill=CARD_BG)
    # WIN vs ENTRY based on market status
    from datetime import datetime, timezone as tz
    is_open_card = True
    try:
        if ts_resolved > 0:
            is_open_card = datetime.now(tz.utc) < datetime.fromtimestamp(ts_resolved, tz=tz.utc)
    except: pass
    # Add sport emoji to question
    sq = _sport_emoji(market_question)
    sq_label = f'{sq} {market_question}' if sq else market_question

    draw.text((PAD, 16), 'POLYSHARK', font=get_font(20, bold=True), fill=TEAL)
    draw.text((PAD + 172, 18), 'FREE TIER', font=f14, fill=MUTED)

    teaser_label = '● FREE PREVIEW'
    tl = draw.textlength(teaser_label, font=f20b)
    draw.rounded_rectangle([WIDTH - PAD - tl - 14, 12, WIDTH - PAD, 44], radius=7, fill=(20, 24, 52))
    draw.text((WIDTH - PAD - tl - 7, 15), teaser_label, font=f20b, fill=TEAL)

    # ── DIRECTION + QUESTION ────────────────────────────────────────────────
    y = 68
    arrow     = '⬆️' if direction.upper() == 'UP' else '⬇️'
    dir_label = f'{arrow} BET {direction.upper()} on '
    draw.text((PAD, y), dir_label, font=f24, fill=WHITE)
    dw     = draw.textlength(dir_label, font=f24)
    q_font = get_font(24, bold=True)
    max_qw = WIDTH - PAD - dw - 10
    words  = sq_label.split()  # with sport emoji
    lines, line = [], []
    for w in words:
        test = ' '.join(line + [w])
        if draw.textlength(test, font=q_font) <= max_qw:
            line.append(w)
        else:
            if line: lines.append(' '.join(line)); line = [w]
            else:   lines.append(w)
    if line: lines.append(' '.join(line))
    draw.text((PAD + dw, y), lines[0], font=q_font, fill=WHITE)
    if len(lines) > 1:
        y += 32
        draw.text((PAD, y), lines[1], font=q_font, fill=WHITE)
    y += 44

    # ── ENTRY PRICE + DATES ──────────────────────────────────────────────────
    divider(draw, y); y += 14

    price_str = f'📊 Entry price: ${entry_price:.4f}' if entry_price < 1 else f'📊 Entry price: ${entry_price:.2f}'
    draw.text((PAD, y), price_str, font=f20b, fill=TEAL)
    y += 36

    if ts_opened:
        divider(draw, y); y += 14
        draw.text((PAD, y), f'📅 O: {fmt_ts(ts_opened, include_time=True)}', font=f16, fill=MUTED)
        y += 30

    if ts_resolved:
        divider(draw, y); y += 14
        draw.text((PAD, y), f'✅ C: {fmt_ts(ts_resolved)}', font=f16, fill=MUTED)
        y += 30

    # ── LINK ────────────────────────────────────────────────────────────────
    if market_url:
        divider(draw, y); y += 14
        draw.text((PAD, y), f'⛓️ {market_url}', font=f16, fill=TEAL)

    # ── FOOTER ──────────────────────────────────────────────────────────────
    footer_y = max(y + 30, 290)
    draw.text((PAD, footer_y + 4), 'Polyshark · Whaletrax', font=f14, fill=(50, 55, 80))
    draw.text((WIDTH - PAD - 160, footer_y + 4), 'Upgrade for full alerts', font=f14, fill=(50, 55, 80))

    # ── GEO RESTRICTION BADGE ───────────────────────────────────────────
    if geo_available == 'NON_US_ONLY':
        geo_lbl = '🇺🇸 US Only'
        geo_col = (50, 130, 255)  # RED
        draw.text((PAD + 200, footer_y + 4), geo_lbl, font=f14, fill=geo_col)
    elif geo_available == 'GLOBAL':
        geo_lbl = '🌍 Global'
        geo_col = (50, 180, 100)  # GREEN
        draw.text((PAD + 200, footer_y + 4), geo_lbl, font=f14, fill=geo_col)
    # UNKNOWN = silent (no badge)

    img.save(img_path, 'PNG')
    print(f'Teaser card saved → {img_path}')
    return img_path


# ─────────────────────────────────────────────────────────────────────────────
#  UNIFIED WRAPPER — used by live_entry_tracker.py / Kai
# ─────────────────────────────────────────────────────────────────────────────
def make_trade_alert_card(
    market_question: str,
    side: str,             # 'BUY' or 'SELL'
    price: float,          # entry price (e.g. 0.62)
    size_usdc: float,      # USDC stake
    masked_name: str = '██████████',
    masked_wallet: str = '0x....abcd',
    trader_pnl: float = 0.0,
    trader_wr: float = 0.0,
    trader_wr_30d: float = 0.0,
    trader_roi: float = 0.0,
    trader_roi_30d: float = 0.0,
    recent_roi: float = 0.0,
    confidence: str = 'HIGH',
    confidence_score: int = 0,   # 0-100 score
    direction_arrow: str = '📈',
    streak: int = 0,
    ts_enter: int = 0,
    ts_exit: int = 0,
    outcome: str = '',
    is_open: bool = True,    # True = ENTRY card, False = WIN card
    geo_available: str = 'UNKNOWN',  # 'GLOBAL' / 'NON_US_ONLY' / 'UNKNOWN'
    img_path: str = '/tmp/polyshark_card.png',
) -> str:
    """Auto-select WIN or LOSS card based on unrealized P&L sign."""
    direction = 'UP' if side.upper() == 'BUY' else 'DOWN'
    is_profit = trader_pnl >= 0
    profit_abs = abs(trader_pnl)
    streak = streak if streak is not None else 0

    if is_profit:
        return generate_card(
            market_question  = market_question,
            direction        = direction,
            profit           = profit_abs,
            roi              = trader_roi,
            size_usdc        = size_usdc,
            masked_wallet    = masked_wallet,
            lifetime_wr      = trader_wr,
            trades_n         = 0,
            current_streak   = streak,
            ts_opened        = ts_enter,
            ts_closes        = ts_exit,
            ts_resolved      = 0,
            market_url       = '',
            whale_badge      = False,
            confidence       = confidence,
            lifetime_roi     = trader_roi,
            roi_30d          = trader_roi_30d,
            confidence_score = confidence_score,
            is_open          = is_open,
            geo_available    = geo_available,
            img_path         = img_path,
        )
    else:
        return generate_loss_card(
            market_question = market_question,
            direction       = direction,
            loss            = profit_abs,
            roi             = trader_roi,
            size_usdc       = size_usdc,
            masked_wallet   = masked_wallet,
            lifetime_wr     = trader_wr,
            lifetime_roi    = trader_roi,
            roi_30d         = trader_roi_30d,
            trades_n        = 0,
            current_streak  = 0,
            ts_opened       = ts_enter,
            ts_closes       = ts_exit,
            ts_resolved     = 0,
            market_url      = '',
            confidence      = confidence,
            is_open         = is_open,
            geo_available   = geo_available,
            img_path        = img_path,
        )


# ── Tests ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import time
    now = int(time.time())
    day = 86400

    # WIN card
    generate_card(
        market_question = 'Will the Dallas Mavericks win the 2026 NBA Finals?',
        direction       = 'UP',
        profit          = 57400,
        roi            = 69,
        size_usdc      = 83200,
        masked_wallet  = '0x....abcd',
        lifetime_wr    = 68,
        trades_n       = 47,
        current_streak = 5,
        ts_opened      = now - 3 * day,
        ts_closes      = now + 5 * day,
        market_url     = 'https://polymarket.com/event/nba-mavs-2026',
        whale_badge    = True,
        confidence     = 'HIGH',
        img_path       = '/tmp/polyshark_alert.png',
    )

    # LOSS card
    generate_loss_card(
        market_question = 'Will Bitcoin exceed $100,000 by end of 2026?',
        direction       = 'DOWN',
        loss            = 8420,
        roi            = -38,
        size_usdc      = 22158,
        masked_wallet  = '0x....8f2a',
        lifetime_wr    = 41,
        trades_n       = 33,
        current_streak = 0,
        ts_opened      = now - 7 * day,
        ts_closes      = now + 2 * day,
        market_url     = 'https://polymarket.com/event/btc-100k-2026',
        confidence     = 'MEDIUM',
        img_path       = '/tmp/polyshark_alert_loss.png',
    )

    # FREE TEASER
    generate_free_teaser(
        market_question = 'Will Ethereum flip Bitcoin by 2027?',
        direction       = 'UP',
        entry_price     = 0.34,
        ts_opened       = now - 1 * day,
        ts_resolved     = now + 30 * day,
        market_url      = 'https://polymarket.com/event/eth-flip-btc',
        img_path        = '/tmp/polyshark_alert_teaser.png',
    )
