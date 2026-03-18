"""
設定：全部從環境變數讀，敏感資訊不寫死。
本機開發時自動載入 .env（若存在）；Docker 環境由 compose 注入，.env 不進 image。
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent

# 載入 .env（python-dotenv 存在才執行，不存在靜默略過）
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

GATEWAY_IP   = os.environ.get("TRADFRI_GATEWAY_IP", "192.168.x.x")
MCP_HOST     = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT     = int(os.environ.get("MCP_PORT", "8765"))
PSK_FILE     = Path(os.environ.get("PSK_FILE",     BASE_DIR / ".tradfri_psk.json"))
DEVICES_FILE = Path(os.environ.get("DEVICES_FILE", BASE_DIR / "devices.json"))
ALIASES_FILE = Path(os.environ.get("ALIASES_FILE", BASE_DIR / "aliases.json"))

# Telegram 推播通知（選填，未設定時靜默略過）
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")   # 格式：123456:AAABBB...
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")     # 格式：數字 ID（如 123456789）

# CoAP OBSERVE 重試間隔（秒）：當 OBSERVE 訂閱中斷後，等待多久重新訂閱。
# 預設 30 秒。此值不影響通知即時性（通知由 gateway push，非輪詢）。
TRADFRI_POLL_INTERVAL = int(os.environ.get("TRADFRI_POLL_INTERVAL", "30"))
