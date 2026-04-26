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

def fmt_ts(ts):
    if not ts: return 'LIVE'
    try:
        return datetime.fromtimestamp(ts, tz=None).strftime('%b %d')
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
    roi: float,              # ROI % (signed)
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
    img_path: str = '/tmp/polyshark_card.png',
) -> str:
    height = 510
    if whale_badge: height += 44
    if current_streak >= 5: height += 40

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
    words  = market_question.split()
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

    draw.text((PAD, y), f'💵 ${abs(profit):,.0f}', font=f32, fill=GREEN)

    roi_str = f'✅ +{roi:.0f}% ROI' if roi >= 0 else f'✅ {roi:.0f}% ROI'
    roi_col = GREEN if roi >= 0 else RED
    draw.text((PAD + 250, y + 6), roi_str, font=f24, fill=roi_col)

    size_str = f'💳 ${size_usdc:,.0f}' if size_usdc < 1_000_000 else f'💳 ${size_usdc/1_000_000:.1f}M'
    sw = draw.textlength(size_str, font=f24)
    draw.text((WIDTH - PAD - sw, y), size_str, font=f24, fill=WHITE)
    y += 44

    # ── WIN RATE ────────────────────────────────────────────────────────────
    divider(draw, y); y += 14
    wr_col, wr_lbl = wr_badge(lifetime_wr)
    if wr_lbl: draw.text((PAD, y), wr_lbl, font=f20b, fill=wr_col)
    if trades_n > 0:
        n_str = f'  n={trades_n}'
        draw.text((PAD + 280, y), n_str, font=f20b, fill=MUTED)
    y += 36

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
    if ts_opened:   parts.append(f'Opened: {fmt_ts(ts_opened)}')
    if ts_closes:   parts.append(f'Closes: {fmt_ts(ts_closes)}')
    if ts_resolved: parts.append(f'Resolved: {fmt_ts(ts_resolved)}')
    draw.text((PAD, y), '  |  '.join(parts), font=f16, fill=MUTED)
    y += 30

    # ── LINKS ───────────────────────────────────────────────────────────────
    if market_url:
        divider(draw, y); y += 14
        draw.text((PAD, y), f'⛓️ {market_url}', font=f16, fill=TEAL)

    # ── FOOTER ──────────────────────────────────────────────────────────────
    footer_y = y + 28
    draw.text((PAD, footer_y + 4), 'Polyshark · Whaletrax', font=f14, fill=(50, 55, 80))
    draw.text((WIDTH - PAD - 180, footer_y + 4), '🔒 Identity anonymized', font=f14, fill=(50, 55, 80))

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
    img_path: str = '/tmp/polyshark_loss_card.png',
) -> str:
    height = 510
    if current_streak >= 5: height += 40

    img  = Image.new('RGB', (WIDTH, height), color=BG)
    draw = ImageDraw.Draw(img)
    f32  = get_font(32, bold=True)
    f24  = get_font(24, bold=True)
    f20b = get_font(20, bold=True)
    f16  = get_font(16)
    f14  = get_font(14)

    # ── HEADER (red accent) ─────────────────────────────────────────────────
    draw.rectangle([0, 0, WIDTH, 58], fill=(30, 14, 14))
    draw.text((PAD, 16), 'POLYSHARK', font=get_font(20, bold=True), fill=RED)
    draw.text((PAD + 172, 18), 'WHALE TRACKER', font=f14, fill=MUTED)

    conf_label = f'● {confidence} CONFIDENCE'
    cw = draw.textlength(conf_label, font=f20b)
    draw.rounded_rectangle([WIDTH - PAD - cw - 14, 12, WIDTH - PAD, 44], radius=7, fill=(40, 14, 14))
    draw.text((WIDTH - PAD - cw - 7, 15), conf_label, font=f20b, fill=RED)

    # ── DIRECTION + QUESTION ────────────────────────────────────────────────
    y = 68
    arrow     = '⬆️' if direction.upper() == 'UP' else '⬇️'
    dir_label = f'{arrow} BET {direction.upper()} on '
    draw.text((PAD, y), dir_label, font=f24, fill=WHITE)
    dw     = draw.textlength(dir_label, font=f24)
    q_font = get_font(24, bold=True)
    max_qw = WIDTH - PAD - dw - 10
    words  = market_question.split()
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

    draw.text((PAD, y), f'🚫 -${abs(loss):,.0f}', font=f32, fill=RED)

    roi_str = f'💲 {roi:.0f}% ROI'
    draw.text((PAD + 250, y + 6), roi_str, font=f24, fill=RED)

    size_str = f'💳 ${size_usdc:,.0f}' if size_usdc < 1_000_000 else f'💳 ${size_usdc/1_000_000:.1f}M'
    sw = draw.textlength(size_str, font=f24)
    draw.text((WIDTH - PAD - sw, y), size_str, font=f24, fill=WHITE)
    y += 44

    # ── WIN RATE ────────────────────────────────────────────────────────────
    divider(draw, y); y += 14
    wr_col, wr_lbl = wr_badge(lifetime_wr)
    if wr_lbl: draw.text((PAD, y), wr_lbl, font=f20b, fill=wr_col)
    if trades_n > 0:
        draw.text((PAD + 280, y), f'  n={trades_n}', font=f20b, fill=MUTED)
    y += 36

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
    if ts_opened:   parts.append(f'Opened: {fmt_ts(ts_opened)}')
    if ts_closes:   parts.append(f'Closes: {fmt_ts(ts_closes)}')
    if ts_resolved: parts.append(f'Resolved: {fmt_ts(ts_resolved)}')
    draw.text((PAD, y), '  |  '.join(parts), font=f16, fill=MUTED)
    y += 30

    # ── LINKS ───────────────────────────────────────────────────────────────
    if market_url:
        divider(draw, y); y += 14
        draw.text((PAD, y), f'⛓️ {market_url}', font=f16, fill=TEAL)

    # ── FOOTER ──────────────────────────────────────────────────────────────
    footer_y = y + 28
    draw.text((PAD, footer_y + 4), 'Polyshark · Whaletrax', font=f14, fill=(50, 55, 80))
    draw.text((WIDTH - PAD - 180, footer_y + 4), '🔒 Identity anonymized', font=f14, fill=(50, 55, 80))

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
    words  = market_question.split()
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
        draw.text((PAD, y), f'📅 Opened: {fmt_ts(ts_opened)}', font=f16, fill=MUTED)
        y += 30

    if ts_resolved:
        divider(draw, y); y += 14
        draw.text((PAD, y), f'✅ Resolved: {fmt_ts(ts_resolved)}', font=f16, fill=MUTED)
        y += 30

    # ── LINK ────────────────────────────────────────────────────────────────
    if market_url:
        divider(draw, y); y += 14
        draw.text((PAD, y), f'⛓️ {market_url}', font=f16, fill=TEAL)

    # ── FOOTER ──────────────────────────────────────────────────────────────
    footer_y = max(y + 30, 290)
    draw.text((PAD, footer_y + 4), 'Polyshark · Whaletrax', font=f14, fill=(50, 55, 80))
    draw.text((WIDTH - PAD - 160, footer_y + 4), 'Upgrade for full alerts', font=f14, fill=(50, 55, 80))

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
    trader_roi: float = 0.0,
    recent_roi: float = 0.0,
    confidence: str = 'HIGH',
    direction_arrow: str = '📈',
    streak: int = 0,
    ts_enter: int = 0,
    ts_exit: int = 0,
    outcome: str = '',
    img_path: str = '/tmp/polyshark_card.png',
) -> str:
    """Auto-select WIN or LOSS card based on unrealized P&L sign."""
    direction = 'UP' if side.upper() == 'BUY' else 'DOWN'
    is_profit = trader_pnl >= 0
    profit_abs = abs(trader_pnl)
    streak = streak if streak is not None else 0

    # Map recent_roi (30d ROI) to roi param (signed)
    roi_pct = recent_roi if trader_pnl >= 0 else -abs(recent_roi)

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
            img_path         = img_path,
        )
    else:
        return generate_loss_card(
            market_question = market_question,
            direction       = direction,
            loss            = profit_abs,
            roi             = abs(roi_pct) if math.isfinite(abs(roi_pct)) else abs(trader_roi),
            size_usdc       = size_usdc,
            masked_wallet   = masked_wallet,
            lifetime_wr     = trader_wr,
            trades_n        = 0,
            current_streak  = 0,
            ts_opened       = ts_enter,
            ts_closes       = ts_exit,
            ts_resolved     = 0,
            market_url      = '',
            confidence      = confidence,
            img_path         = img_path,
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
