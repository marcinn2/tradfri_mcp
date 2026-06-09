"""
Configuration: all values from environment variables, no hardcoded secrets.
Loads .env automatically for local development; Docker gets vars injected by compose, .env stays out of the image.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent

# Load .env if python-dotenv is available, silently skip otherwise
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

GATEWAY_IP   = os.environ["TRADFRI_GATEWAY_IP"]
MCP_HOST     = os.environ.get("MCP_HOST", "0.0.0.0")
MCP_PORT     = int(os.environ.get("MCP_PORT", "8765"))
PSK_FILE     = Path(os.environ.get("PSK_FILE",     BASE_DIR / ".tradfri_psk.json"))
DEVICES_FILE = Path(os.environ.get("DEVICES_FILE", BASE_DIR / "devices.json"))
ALIASES_FILE = Path(os.environ.get("ALIASES_FILE", BASE_DIR / "aliases.json"))
# Optional bearer token — if set, every HTTP request must carry Authorization: Bearer <token>
MCP_AUTH_TOKEN: str | None = os.environ.get("MCP_AUTH_TOKEN") or None
# Escape hatch: allow binding to a non-loopback host with no auth token (trusted LAN only)
MCP_ALLOW_INSECURE = os.environ.get("MCP_ALLOW_INSECURE", "").lower() in ("1", "true", "yes")

