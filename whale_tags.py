import json, os

HP_FILE = os.path.join(os.path.dirname(__file__), 'high_priority_whales.json')

def is_high_priority(wallet: str) -> bool:
    """Check if wallet is in the high-priority watchlist."""
    if not os.path.exists(HP_FILE):
        return False
    whales = json.load(open(HP_FILE))
    return any(w.lower() == wallet.lower() for w in whales.get('wallets', []))

def get_whale_label(wallet: str, display_name: str) -> str:
    """Return special badge if high-priority, else display name."""
    if is_high_priority(wallet):
        return '\u0001f3c6 HIGH-FREQ WINNING WHALE \u0001f3c6'
    return display_name or 'Anonymous Whale'
