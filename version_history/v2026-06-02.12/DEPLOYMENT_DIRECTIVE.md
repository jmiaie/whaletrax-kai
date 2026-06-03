# Deployment Directive: Integrate Polymarket US Copy-Trading Execution
**Received:** 2026-06-02 17:47 UTC | **Version:** v2026-06-02.12 Checkpoint

---

## Role & Context
Kai is the execution gateway for tracking pipelines on this VM:
- **whaletrax** — on-chain tracking and log monitoring
- **polyshark** — wallet signal processing and data normalization

Kai ingests signal data from polyshark, enforces compliance checks, and executes copy-trades autonomously.

---

## Environment Setup

```bash
pip install polymarket-us python-dotenv
```

### Required Env Vars
```env
POLYMARKET_KEY_ID=your-uuid-style-api-key-id
POLYMARKET_SECRET_KEY=your-base64-ed25519-private-key
```

---

## Skill: PolyShark Execution Engine

**Path:** `~/.openclaw/workspace/skills/polyshark/SKILL.md`

### execute_polymarket_us_trade

```python
import os
from polymarket_us import PolymarketUS

def execute_polymarket_us_trade(market_slug: str, intent: str, price_usd: float, quantity: int) -> str:
    key_id = os.getenv("POLYMARKET_KEY_ID")
    secret_key = os.getenv("POLYMARKET_SECRET_KEY")

    if not key_id or not secret_key:
        return "error: missing required polymarket us credentials in system environment context."

    intent_map = {
        "BUY_LONG": "ORDER_INTENT_BUY_LONG",
        "BUY_SHORT": "ORDER_INTENT_BUY_SHORT",
        "SELL_LONG": "ORDER_INTENT_SELL_LONG",
        "SELL_SHORT": "ORDER_INTENT_SELL_SHORT"
    }
    mapped_intent = intent_map.get(intent.upper(), "ORDER_INTENT_BUY_LONG")

    try:
        with PolymarketUS(key_id=key_id, secret_key=secret_key, timeout=10.0) as client:
            order = client.orders.create({
                "marketSlug": market_slug,
                "intent": mapped_intent,
                "type": "ORDER_TYPE_LIMIT",
                "price": {"value": str(price_usd), "currency": "USD"},
                "quantity": int(quantity),
                "tif": "TIME_IN_FORCE_GOOD_TILL_CANCEL",
            })
            if order and "id" in order:
                return f"success: copy trade filled on us book. order_id: {order['id']}"
            return f"failure: order submission returned empty response state: {order}"
    except Exception as e:
        return f"runtime execution failure encountered by agent tool: {str(e)}"
```

---

## Operational Rules

| Rule | Details |
|------|---------|
| **Proxy Wallet Mapping** | whaletrax monitors Polygon (0xE11118...) → map to actual Polymarket proxy wallets |
| **Intent Conversion** | YES share → `BUY_LONG` \| NO share → `BUY_SHORT` |
| **Slippage Buffer** | +$0.01 to +$0.02 offset above target wallet's execution price |
| **Execution Logs** | All orders → persistent ledger in workspace for performance tracing |

---

## Next Steps for Kai

1. Confirm env file access
2. Verify `polymarket-us` library installation in runtime
3. Inject skill module into active system capabilities

---

**Checkpoint:** v2026-06-02.12 | All current files snapshotted to `version_history/v2026-06-02.12/`
**Status:** SETUP PENDING — awaiting POLYMARKET_KEY_ID + POLYMARKET_SECRET_KEY