"""
Polyshark Telegram Alert Sender

Sends whale trade alerts to the Polyshark Telegram channel via @jefe_swarm2bot (display name: Polysharkbot/Swarm2bot).
Can be called by whaletrax, kronos, or any other signal generator.
"""

import sys
import os
import json
import argparse
from datetime import datetime

# Add whaletrax to path for alert card generation
sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/repos/whaletrax')

try:
    import requests
except ImportError:
    print("Installing requests...")
    os.system("pip3 install requests -q")
    import requests

# Bot token for @jefe_swarm2bot (WhaleTrax broadcast bot)
BOT_TOKEN = "8741871021:AAF_OJ0rkE5T_bq4YXT_RPUwWG07bYs8I3g"
# Channel ID for Polyshark broadcasts
CHANNEL_ID = "-1003999194095"

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_text(message: str, parse_mode: str = "Markdown") -> dict:
    """Send a text message to the Polyshark channel."""
    url = f"{BASE_URL}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    response = requests.post(url, json=payload, timeout=10)
    return response.json()


def send_photo(photo_path: str, caption: str = None, parse_mode: str = "Markdown") -> dict:
    """Send a photo (alert card image) to the Polyshark channel."""
    url = f"{BASE_URL}/sendPhoto"
    payload = {
        "chat_id": CHANNEL_ID,
        "parse_mode": parse_mode
    }
    data = {"caption": caption} if caption else {}
    with open(photo_path, "rb") as f:
        files = {"photo": f}
        response = requests.post(url, data=data, files=files, timeout=30)
    return response.json()


def send_alert_card(
    image_path: str,
    trader_name: str = "██████████",
    trader_wallet: str = "0x....abcd",
    market_question: str = "Unknown Market",
    trade_type: str = "BUY",
    trade_price: float = 0.0,
    position_size: float = 0.0,
    pnl_all_time: float = 0.0,
    win_rate: float = 0.0,
    roi_30d: float = 0.0,
    streak_count: int = 0,
    confidence: str = "HIGH",
    kronos_signal: dict = None
) -> dict:
    """
    Generate and send a full Polyshark alert card.
    
    Args:
        image_path: Path to the alert card PNG
        All other args: whale trade data + optional Kronos signal
    
    Returns:
        Telegram API response dict
    """
    # Build caption with signal info
    caption = f"""🐋 *POLYSHARK WHALE ALERT*
━━━━━━━━━━━━━━━━━━
📊 *{market_question[:60]}...*
━━━━━━━━━━━━━━━━━━
[{trade_type}] ${trade_price:.2f} → Position: ${position_size:,.0f}
━━━━━━━━━━━━━━━━━━
👤 {trader_name} | {trader_wallet}
📈 All-Time P&L: ${pnl_all_time:,.0f} ({win_rate:.1f}% WR)
📉 30D ROI: {roi_30d:+.1f}%"""
    
    if streak_count > 0:
        caption += f"\n🔥 {streak_count} CORRECT IN A ROW"
    
    if kronos_signal:
        direction = kronos_signal.get('direction', 'NEUTRAL')
        emoji = {'UP': '📈', 'DOWN': '📉', 'NEUTRAL': '➡️'}.get(direction, '➡️')
        conf = kronos_signal.get('confidence', 0)
        predicted = kronos_signal.get('predicted_price', 0)
        caption += f"\n━━━━━━━━━━━━━━━━━━"
        caption += f"\n🤖 *KRONOS FORECAST* {emoji}"
        caption += f"\n   Direction: {direction} ({conf:.0%} confidence)"
        caption += f"\n   Predicted: ${predicted:.4f}"
    
    # Send photo card
    if os.path.exists(image_path):
        result = send_photo(image_path, caption)
    else:
        # Fallback to text-only
        result = send_text(caption)
    
    return result


def test_connection() -> bool:
    """Test if the bot can reach the channel."""
    try:
        # Try to get chat info
        url = f"{BASE_URL}/getChat?chat_id={CHANNEL_ID}"
        response = requests.get(url, timeout=10)
        data = response.json()
        if data.get('ok'):
            chat = data.get('result', {})
            print(f"✅ Connected to channel: {chat.get('title', 'Unknown')}")
            return True
        else:
            print(f"❌ Channel access denied: {data.get('description', 'Unknown error')}")
            return False
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False


def demo_alert():
    """Send a demo alert to verify the setup."""
    print("Sending demo alert to Polyshark channel...")
    
    # Generate demo alert card
    from alerts.polyshark_alert import make_trade_alert_card
    
    demo_data = {
        'question': 'Will Bitcoin exceed $100,000 by June 30, 2025?',
        'price': 0.62,
        'size': 12500,
        'side': 'BUY',
        'trader': '██████████',
        'wallet': '0x....abcd',
        'pnl': 284750,
        'won': True,
        'streak': 7
    }
    
    card_path = make_trade_alert_card(**demo_data)
    print(f"Generated card: {card_path}")
    
    # Send it
    result = send_alert_card(
        image_path=card_path,
        trader_name="██████████",
        trader_wallet="0x....abcd",
        market_question="Will Bitcoin exceed $100,000 by June 30, 2025?",
        trade_type="BUY",
        trade_price=0.62,
        position_size=12500,
        pnl_all_time=284750,
        win_rate=61.4,
        roi_30d=32.5,
        streak_count=7,
        confidence="HIGH"
    )
    
    if result.get('ok'):
        print("✅ Demo alert sent successfully!")
    else:
        print(f"❌ Failed: {result}")
    
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Polyshark Telegram Alert Sender")
    parser.add_argument("--test", action="store_true", help="Test bot connection")
    parser.add_argument("--demo", action="store_true", help="Send demo alert card")
    parser.add_argument("--image", type=str, help="Path to alert card image")
    parser.add_argument("--caption", type=str, help="Alert caption text")
    
    args = parser.parse_args()
    
    if args.test:
        success = test_connection()
        sys.exit(0 if success else 1)
    elif args.demo:
        demo_alert()
    elif args.image:
        result = send_photo(args.image, args.caption)
        print(result)
    else:
        # Default: test connection
        test_connection()