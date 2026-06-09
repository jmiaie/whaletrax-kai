"""
QC Module — quality gate for card accuracy and math validation.
Runs between format_card() and send(). Catches math errors, wrong prices,
and broken calculations BEFORE they go out. Auto-fixes what it can;
pauses and alerts the team for anything it can't.
"""

from __future__ import annotations
import re, time
from datetime import datetime, timezone
from pathlib import Path

log = __import__('logging').getLogger('polyshark_qc')

PAUSE_FILE  = Path('/tmp/polyshark_router_paused')
QC_ALERT_CH = '-1003786930778'   # Hub channel for QC alerts
MAX_RETRIES = 2


# ── Core gate ─────────────────────────────────────────────────────────────────

def qc_check_card(bw, card_text: str, tier: str) -> tuple[bool, str, list[str]]:
    """
    Validate a card before send. Returns (pass, card_text, fixes_applied).

    pass=False → do NOT send; card is paused.
    pass=True  → card is clean (or was auto-fixed); proceed to send.
    """
    if not card_text:
        return False, card_text, ['empty_card']

    issues: list[str] = []
    fixed_card = card_text

    for attempt in range(MAX_RETRIES):
        issues = []

        # Check 1: ROI math
        issues += _check_roi_math(bw, fixed_card)

        # Check 2: Now: price matches correct outcome side
        issues += _check_now_price(bw, fixed_card)

        # Check 3: Win rate consistency
        issues += _check_win_rate(bw, fixed_card)

        # Check 4: No duplicate code blocks
        issues += _check_no_duplicates(fixed_card)

        # Check 5: Outcome / direction consistency
        issues += _check_outcome_direction(bw, fixed_card)

        # Check 6: P/L sign matches ROI sign
        issues += _check_pnl_sign(bw, fixed_card)

        if not issues:
            return True, fixed_card, []

        # Auto-fix attempt
        fixed_card = _auto_fix(bw, fixed_card, issues)
        if fixed_card and fixed_card != card_text:
            log.info(f'QC auto-fixed [{attempt+1}]: {issues}')
            continue
        break

    # Exhausted retries — pause and alert
    _pause_and_alert(bw, card_text, issues)
    return False, card_text, issues


# ── Individual checks ──────────────────────────────────────────────────────────

def _check_roi_math(bw, card_text: str) -> list[str]:
    """Verify roi_pct and profit_usdc are consistent with entry price and direction."""
    issues = []
    entry_px = float(getattr(bw, 'avg_price', 0) or 0)
    roi_pct  = float(getattr(bw, 'roi_pct', 0) or 0)
    profit   = float(getattr(bw, 'profit_usdc', 0) or 0)
    trade_sz = float(getattr(bw, 'trade_size_usdc', 0) or 0)
    is_open  = bool(getattr(bw, 'is_open', True))

    if entry_px <= 0 or entry_px >= 1:
        return []  # can't sanity-check without valid entry price

    # roi_pct should be in a plausible range (-100, +50000) for open positions
    if is_open and (roi_pct < -99 or roi_pct > 50000):
        issues.append(f'roi_extreme: roi_pct={roi_pct:.2f}% outside plausible range')

    # profit = trade_sz * roi_pct/100 should roughly match profit_usdc
    if trade_sz > 0 and abs(profit) > 0:
        expected_roi = (profit / trade_sz) * 100
        if abs(expected_roi - roi_pct) > 200 and abs(roi_pct) > 1:
            issues.append(
                f'roi_mismatch: profit={profit:.0f} on size={trade_sz:.0f} '
                f'implies roi={expected_roi:.1f}% but card shows roi_pct={roi_pct:.2f}%'
            )

    # Plausibility: profit should be roughly (trade_sz / entry_px) - trade_sz for closed
    if not is_open and trade_sz > 0 and entry_px > 0:
        max_profit = (trade_sz / entry_px) - trade_sz
        if profit > max_profit * 1.5:
            issues.append(
                f'profit_too_high: profit={profit:.0f} exceeds max plausible '
                f'{max_profit:.0f} for entry={entry_px:.3f}, size={trade_sz:.0f}'
            )

    return issues


def _check_now_price(bw, card_text: str) -> list[str]:
    """
    Verify 'Now: Xc' shows the correct outcome price.
    BET YES → Now: should show YES price (yes_price)
    BET NO  → Now: should show NO price (no_price)
    """
    issues = []

    now_match = re.search(r'Now:\s*([\d.]+)¢', card_text)
    if not now_match:
        return []  # no Now: line = fine

    now_cents = float(now_match.group(1))
    side_raw  = str(getattr(bw, 'outcome', '') or '').upper()
    if side_raw in ('YES', 'NO', 'DOWN'):
        bet_side = 'YES' if side_raw not in ('DOWN', 'NO') else 'NO'
    else:
        cur_p = float(getattr(bw, 'current_price', 0) or 0)
        bet_side = 'YES' if cur_p >= 0.5 else 'NO'

    if bet_side == 'YES':
        ref_price = float(getattr(bw, 'yes_price', 0) or 0)
    else:
        ref_price = float(getattr(bw, 'no_price', 0) or 0)

    if ref_price > 0:
        ref_cents = ref_price * 100
        if abs(now_cents - ref_cents) > 5:
            issues.append(
                f'now_price_wrong: card shows Now:{now_cents:.1f}¢ but '
                f'expected {ref_cents:.1f}¢ for BET {bet_side} '
                f'(yes={getattr(bw,"yes_price",0)*100:.1f}¢, no={getattr(bw,"no_price",0)*100:.1f}¢)'
            )

    return issues


def _check_win_rate(bw, card_text: str) -> list[str]:
    """Verify WR% matches wins/total when both are shown."""
    issues = []

    wr_match = re.search(r'(\d+)%\s*WR\s*\((\d+)/(\d+)\)', card_text)
    if wr_match:
        card_wr  = int(wr_match.group(1))
        wins = int(wr_match.group(2))
        total    = int(wr_match.group(3))
        if total > 0:
            computed = round(wins / total * 100)
            if abs(computed - card_wr) > 2:
                issues.append(
                    f'wr_mismatch: card shows {card_wr}% WR ({wins}/{total}) '
                    f'but {wins}/{total}={computed}% — recompute needed'
                )

    return issues


def _check_no_duplicates(card_text: str) -> list[str]:
    """Detect duplicate code/text blocks in the card body."""
    issues = []
    lines = card_text.split('\n')

    seen_lines: dict = {}
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith('—') and len(stripped) > 10:
            if stripped in seen_lines and i - seen_lines[stripped] == 1:
                issues.append(f'duplicate_line: "{stripped[:50]}" appears twice consecutively')
            seen_lines[stripped] = i

    compound_issues = [
        'pos_30d', 'bw_pos_30', 'wins_30', 'wins_lt',
        'inverse_reason', 'recent_line', 'lifetime_line',
    ]
    for keyword in compound_issues:
        count = card_text.count(keyword)
        if count > 1:
            issues.append(f'duplicate_block: "{keyword}" appears {count} times in card')

    return issues


def _check_outcome_direction(bw, card_text: str) -> list[str]:
    """Verify BET YES/NO matches the outcome and price logic."""
    issues = []

    side_raw = str(getattr(bw, 'outcome', '') or '').upper()
    if side_raw in ('YES', 'NO', 'DOWN'):
        bet_side = 'YES' if side_raw not in ('DOWN', 'NO') else 'NO'
    else:
        cur_p = float(getattr(bw, 'current_price', 0) or 0)
        bet_side = 'YES' if cur_p >= 0.5 else 'NO'

    bet_match = re.search(r'BET\s+(YES|NO)', card_text)
    if bet_match:
        card_side = bet_match.group(1)
        if card_side != bet_side:
            issues.append(
                f'outcome_mismatch: bw.outcome implies BET {bet_side} '
                f'but card shows BET {card_side}'
            )

    return issues


def _check_pnl_sign(bw, card_text: str) -> list[str]:
    """Verify P/L sign (+/-) matches ROI sign."""
    issues = []

    profit = float(getattr(bw, 'profit_usdc', 0) or 0)
    roi_pct = float(getattr(bw, 'roi_pct', 0) or 0)

    if profit == 0 and roi_pct == 0:
        return []

    if profit > 0 and roi_pct < 0:
        issues.append(f'pnl_sign_mismatch: profit={profit:.0f} (positive) but roi_pct={roi_pct:.2f}% (negative)')
    if profit < 0 and roi_pct > 0:
        issues.append(f'pnl_sign_mismatch: profit={profit:.0f} (negative) but roi_pct={roi_pct:.2f}% (positive)')

    pnl_dollar_match = re.search(r'[💰💵]\s*([+-])?\$', card_text)
    if pnl_dollar_match and profit != 0:
        sign_char = pnl_dollar_match.group(1) or '+'
        shown_positive = sign_char == '+'
        should_be_positive = profit > 0
        if shown_positive != should_be_positive:
            issues.append(
                f'pnl_sign_card: card shows {sign_char}$ but '
                f'profit_usdc={profit:.0f} → expected {"+" if should_be_positive else "-"}$'
            )

    return issues


# ── Auto-fix ─────────────────────────────────────────────────────────────────

def _auto_fix(bw, card_text: str, issues: list[str]) -> str | None:
    """Attempt to fix known issues automatically. Returns None if nothing fixed."""
    import re as _re

    fixed = card_text

    for issue in issues:
        if 'now_price_wrong' in issue:
            side_raw = str(getattr(bw, 'outcome', '') or '').upper()
            bet_side = 'YES' if side_raw not in ('DOWN', 'NO') else 'NO'
            if bet_side == 'NO' and getattr(bw, 'market_id', None):
                try:
                    import urllib.request, json as _json
                    url = f"https://clob.polymarket.com/markets/{bw.market_id}"
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        data = _json.loads(resp.read())
                    for tok in data.get('tokens', []):
                        if str(tok.get('outcome', '')).lower() == 'no':
                            p = float(tok.get('price', 0) or 0)
                            if p > 0:
                                bw.no_price = p
                                now_cents = p * 100
                                fixed = _re.sub(r'Now:\s*[\d.]+¢', f'Now: {now_cents:.1f}¢', fixed)
                                log.info(f'QC auto-fix: updated Now: to {now_cents:.1f}¢ for BET NO')
                                break
                except Exception as e:
                    log.warning(f'QC now_price auto-fix failed: {e}')

        elif 'roi_mismatch' in issue or 'roi_extreme' in issue:
            profit = float(getattr(bw, 'profit_usdc', 0) or 0)
            trade_sz = float(getattr(bw, 'trade_size_usdc', 0) or 0)
            if trade_sz > 0 and abs(profit) > 0:
                new_roi = (profit / trade_sz) * 100
                bw.roi_pct = new_roi
                fixed = _re.sub(r'\([+-]?[\d.]+%[^)]*\)', f'({new_roi:+.2f}% potential ROI)', fixed)
                log.info(f'QC auto-fix: recomputed roi_pct={new_roi:.2f}% from profit/size')

        elif 'wr_mismatch' in issue:
            wr_match = _re.search(r'(\d+)%\s*WR\s*\((\d+)/(\d+)\)', fixed)
            if wr_match:
                wins = int(wr_match.group(2))
                total = int(wr_match.group(3))
                if total > 0:
                    computed = round(wins / total * 100)
                    fixed = _re.sub(r'\d+%\s*WR\s*\(\d+/\d+\)', f'{computed}% WR ({wins}/{total})', fixed)
                    log.info(f'QC auto-fix: corrected WR to {computed}% ({wins}/{total})')

        elif 'pnl_sign_mismatch' in issue or 'pnl_sign_card' in issue:
            profit = float(getattr(bw, 'profit_usdc', 0) or 0)
            sign = '+' if profit >= 0 else '-'
            fixed = _re.sub(r'([💰💵])\s*([+-])?\$', rf'\1 {sign}$', fixed)
            log.info(f'QC auto-fix: corrected P/L sign to {sign}')

    return fixed if fixed != card_text else None


# ── Pause + alert ─────────────────────────────────────────────────────────────

def _pause_and_alert(bw, card_text: str, issues: list[str]) -> None:
    """Create pause file and alert the team with full details."""
    PAUSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PAUSE_FILE.touch()
    log.warning(f'QC FAILED — router PAUSED. Issues: {issues}')

    market  = getattr(bw, 'market_question', '') or getattr(bw, 'market_id', '') or '?'
    wallet  = getattr(bw, 'wallet', '') or '?'
    entry   = float(getattr(bw, 'avg_price', 0) or 0)
    roi     = float(getattr(bw, 'roi_pct', 0) or 0)
    profit  = float(getattr(bw, 'profit_usdc', 0) or 0)
    side    = getattr(bw, 'outcome', '') or '?'
    now_yes = float(getattr(bw, 'yes_price', 0) or 0)
    now_no  = float(getattr(bw, 'no_price', 0) or 0)
    ts      = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    issue_text = '\n'.join(f'  ⚠️ {iss}' for iss in issues)

    alert = (
        f"🛑 QC GATE FAILED — ROUTER PAUSED\n"
        f"{'━'*40}\n"
        f"🕐 {ts}\n"
        f"📋 {market[:80]}\n"
        f"👤 {wallet[:20]}\n"
        f"📌 BET: {side} | Entry: {entry*100:.1f}¢\n"
        f"💰 ROI: {roi:+.2f}% | Profit: {profit:+.0f}\n"
        f"📊 Live: YES={now_yes*100:.1f}¢ | NO={now_no*100:.1f}¢\n"
        f"{'━'*40}\n"
        f"ISSUES FOUND:\n{issue_text}\n"
        f"{'━'*40}\n"
        f"To resume: rm /tmp/polyshark_router_paused"
    )

    try:
        import requests
        token_file = Path('/home/ubuntu/.openclaw/.secrets/polyshark.env')
        token = None
        if token_file.exists():
            for line in token_file.read_text().splitlines():
                if line.startswith('TELEGRAM_BOT_TOKEN='):
                    token = line.split('=', 1)[1].strip()
        if token:
            requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': QC_ALERT_CH, 'text': alert, 'parse_mode': 'HTML',
                      'disable_web_page_preview': True},
                timeout=20,
            )
    except Exception as e:
        log.error(f'QC alert send failed: {e}')