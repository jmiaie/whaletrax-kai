# Polyshark Card Format Spec

**Version:** 1.2 | **Updated:** 2026-04-25 19:39 UTC
**Changes:** Integrated Jeff's formatting specs - profit/ROI colors, directional arrows, WR color badges, wallet emoji, link emoji, confidence score

---

## Card Types

| Card Type | Tier | When it fires |
|-----------|------|---------------|
| **PRO Card** | PRO / Hub | All whale alerts go to Hub immediately |
| **Category Card** | Category | Same content, forwarded to Sports / eSports / Crypto / etc. at 10-min delay |
| **Curated Card** | Free | Full PRO card sent to free tier at 15 min (qualifying picks only) |
| **Free Teaser Card** | Free | Stripped card — Play + Direction + Entry/Opened/Resolved dates |

---

## CRITICAL: Data Validation Rules

**Before any card is sent, these MUST be checked:**

### $0.0000 = REJECT ❌
- Any alert with entry price `$0.0000` → REJECT at source, do NOT send
- This filter applies at Swarm2bot level, not downstream
- Log all rejections for audit

### Stock Tickers = REJECT ❌
- $AMAZON, $YELLEN, $YHOO, or any stock ticker → REJECT
- These are NOT Polymarket markets

### Resolved Markets = REJECT ❌
- Markets that have already resolved (2024 election, etc.) → REJECT
- Only active, unresolved markets generate alerts

### Real Data Only ✅
- Entry price must be > $0.0000 from actual on-chain data
- P&L must reflect actual wallet balance/position — NO generated numbers
- Volume must be real — no repeating identical amounts

### Valid Polymarket URL Required
- Only real Polymarket URLs included in cards
- Format: `https://polymarket.com/event/{slug}`
- Telegram auto-generates preview from valid URLs
- If no valid Polymarket URL exists → REJECT the alert

---

## PRO Card Fields — INTEGRATED FORMAT v1.2

```
🏅 [WHALE BADGE]

🎯 [MARKET QUESTION]

✅ $57,188 | ✅ +69% ROI
⬆️ BET UP on [outcome]
🏆 🟢 68%+ lifetime WR | 🔥 5-win streak
📊 75% WR (30d) | n=47

💰 Profit: +$847 | 💳 Size: $5,200

⏰ Opened: Apr 22 | Closes: Apr 26
⛓️ [polymarket.com/event/...]
🐋 0xa5ef...2966

[Confidence: 87%]                          ← if available
```

### Field Definitions

| Field | Example | Notes |
|-------|---------|-------|
| `WHALE BADGE` | `🏅 HIGH-FREQ WINNING WHALE 🏅` | Only for tagged whales (whale_tags.json) |
| `MARKET QUESTION` | "Will Club Atlético de Madrid win on 2026-04-22?" | Full question text |
| `✅ $57,188 \| ✅ +69% ROI` | Profit + ROI, both green with ✅ | Only shown if both available |
| `⬆️ BET UP on [outcome]` | Directional + outcome name | Can be UP/DOWN, YES/NO, team name |
| `🏆 🟢 68%+ lifetime WR` | WR with color badge | 🟢≥65%, 🟠45-64%, 🔴<40% |
| `🔥 5-win streak` | Current streak count | 🔥🔥 8+ = ON FIRE |
| `📊 75% WR (30d) | n=47` | 30d win rate + trade count |
| `💰 Profit: +$847` | Realized PnL | From on-chain |
| `💳 Size: $5,200` | Trade size in USDC | |
| `⏰ Opened/Closes` | Dates | Blockchain timestamps |
| `⛓️ [URL]` | Polymarket link | Chains emoji + URL |
| `🐋 0xa5ef...2966` | Wallet address | Truncated, whale emoji |
| `Confidence: 87%` | Internal score | Shown in brackets if available |

---

## LOSS Card Format

```
🏅 [WHALE BADGE]

🎯 [MARKET QUESTION]

💰 $8,420 | 💲 -38% ROI
⬇️ BET DOWN on NO
🏆 🟠 41%~ lifetime WR | 🔴 28% 30d WR

💰 Loss: -$420 | 💳 Size: $1,100

⏰ Opened: Apr 20 | Closes: Apr 25
⛓️ [polymarket.com/event/...]
🐋 0xa5ef...2966

[Confidence: 87%]
```

### Loss Indicators

| Field | Loss Display | Notes |
|-------|-------------|-------|
| **Profit** | `💰 $8,420` | Red, no + sign |
| **ROI** | `💲 -38% ROI` | Red with stop sign emoji |
| **Direction** | `⬇️ BET DOWN on NO` | Down arrow |
| **Lifetime WR** | `🏆 🟠 41%~` | Amber (45-64%) |
| **30d WR** | `🔴 28% 30d WR` | Red (<40%) |

---

## Color Key

| Color | Emoji | Meaning | Trigger |
|-------|-------|---------|---------|
| **Green** | 🟢 / ✅ | Positive | Profit, WR ≥65%, positive ROI |
| **Amber** | 🟠 / 💲 | Neutral/Warning | WR 45-64%, break-even |
| **Red** | 🔴 / 🛑 | Negative | Loss, WR <40%, negative ROI |

---

## Free Teaser Card Fields

```
🎯 [MARKET QUESTION]
⬆️ BET UP on [outcome]

📊 Entry price: $0.560
📅 Opened: Apr 22
✅ Resolved: [date]
⛓️ [polymarket.com/event/...]
```

**Stripped** — no profit, no ROI, no win rate. Shows only: Play, Direction, Entry Price, Opened Date, Resolution link.

**Critical: Direction AND Play must both be shown.** Do not show "N/A" or leave blank.

---

## Sports / eSports Routing

**Physical Sports → Sports channel**
- Requires anchor word: vs, game, score, playoff, nba, nfl, etc.
- Prevents false positives: "Celtic knots" won't route to Sports

**eSports → eSports channel**
- No anchor required — org names inherently gaming context
- Teams: Cloud9, T1, G2, NAVI, Fnatic, Sentinels, etc.

**Team databases:**
- `keywords/sports_teams.md` — 300+ physical sports teams
- `keywords/esports_teams.md` — 90+ esports teams/orgs

---

## Card Formatting Rules

- Use `——————————` (plain dashes) — NOT box-drawing unicode
- Use HTML parse mode (`parse_mode=HTML`) — NOT MarkdownV2
- Emoji must be bare: `⚔️` not `:crossed_swords:`
- All links: `disable_web_page_preview: True`
- Telegram auto-generates link previews from valid Polymarket URLs

---

## Reject Flow

```
Alert Triggered
      ↓
[Check: Entry price = $0.0000?] → YES → REJECT
      ↓ NO
[Check: Stock ticker detected?] → YES → REJECT
      ↓ NO
[Check: Market resolved?] → YES → REJECT
      ↓ NO
[Check: Real Polymarket URL exists?] → NO → REJECT
      ↓ YES
[Check: Real on-chain data?] → NO → REJECT
      ↓ YES
[Route to Kai dedup]
      ↓
[Forward to appropriate channel]
```

---

## Win Rate Color Badge Rules

| WR Range | Badge | Usage |
|----------|-------|-------|
| ≥65% | 🟢 | Strong - show `+` sign e.g., `68%+` |
| 45-64% | 🟠 | Average - show `~` sign e.g., `41%~` |
| <40% | 🔴 | Below average - show `-` sign e.g., `28%-` |

---

## Competitor Benchmark (Reference)

Prediction Shark (~$40K MRR) card format:
```
🐋 Prediction Shark Alert
📋 Will Club Atlético de Madrid win on 2026-04-22?
🟢 BUY YES @ $0.560 — $1321 USDC
📊 75% WR (30d) | +30% ROI (30d)
🔗 https://polymarket.com/event/lal-elc-mad-2026-04-22
```

Key elements we adopted:
- 🟢BUY YES @ price format
- — $USDC stake display
- 📊 WR + ROI on one line

---

## Confidence Score — INTERNAL ONLY

- `detect_categories_with_confidence` logs: `Category forward (sports) [score=3]: ...`
- Score is shown in cards as `[Confidence: 87%]` when available
- Jeff can review full logs on demand

---

*Spec version 1.2 — Built 2026-04-25 by KaiOC 🌊*
*Updates: Integrated Jeff's formatting specs - profit/ROI colors, directional arrows, WR color badges, wallet emoji, link emoji, confidence score, loss card format*