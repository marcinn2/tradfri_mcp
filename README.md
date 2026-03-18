# kc_tradfri_mcp

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![FastMCP](https://img.shields.io/badge/FastMCP-3.x-orange.svg)](https://github.com/jlowin/fastmcp)
[![MCP](https://img.shields.io/badge/Protocol-MCP-purple.svg)](https://modelcontextprotocol.io)

[繁體中文](README_zh.md)

MCP Server for IKEA TRADFRI smart home gateway. Wraps CoAP-over-DTLS into MCP tools so AI assistants can control lights, plugs, and scenes via natural language.

> **Full tutorial**: [`docs/openclaw-tradfri-mcp-tutorial.md`](docs/openclaw-tradfri-mcp-tutorial.md)
> **DTLS pitfalls on macOS**: [`docs/dtls-tradfri-pitfalls.md`](docs/dtls-tradfri-pitfalls.md)

---

## Architecture

```
User (Telegram / Web UI)
  -> AI Agent (OpenClaw / Claude Desktop / etc.)
  -> mcporter CLI (MCP client)
  -> tradfri-mcp (Docker, FastMCP HTTP server, port 8765)
  -> aiocoap (CoAP over DTLS)
  -> TRADFRI gateway (LAN, UDP 5684)
  -> Zigbee -> Lights / Plugs
```

## Features

- **Natural language control** — "turn on the living room lights" just works
- **12 MCP tools** — on/off, brightness, color temp, color, scenes, status, and more
- **Alias system** — map friendly names to devices, groups, or virtual rooms
- **CoAP OBSERVE push notifications** — get notified via Telegram when lights change (e.g. via remote or Apple Home)
- **Docker-ready** — `docker compose up -d` with log rotation
- **Vendored TinyDTLS** — patched for macOS; no OpenSSL 3 dependency

## Project Structure

```
kc_tradfri_mcp/
├── server.py              # FastMCP HTTP server (main entry)
├── coap_client.py         # aiocoap wrapper (CoAP GET/PUT, singleton context)
├── config.py              # Environment variable config
├── devices.py             # Device topology (devices.json / aliases.json)
├── aliases.json           # Custom aliases (incl. virtual rooms)
├── .tradfri_psk.json      # PSK credentials (.gitignore)
├── .env / .env.example    # Environment variables
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml / uv.lock
├── vendor/dtlssocket/     # DTLSSocket 0.2.3 (TinyDTLS patched for macOS)
├── scripts/
│   ├── gen_psk.py         # Generate PSK credentials
│   └── scan.py            # Scan gateway devices
├── openclaw-skill/        # OpenClaw skill (see "OpenClaw Integration")
│   ├── SKILL.md
│   ├── _meta.json
│   ├── .clawhub/origin.json
│   └── scripts/
│       └── tradfri        # Wrapper script (simplifies mcporter calls)
└── docs/
    ├── dtls-tradfri-pitfalls.md
    └── openclaw-tradfri-mcp-tutorial.md
```

---

## Quick Start

### 1. Clone and install dependencies

```bash
git clone https://github.com/KerberosClaw/kc_tradfri_mcp.git
cd kc_tradfri_mcp
uv sync
```

### 2. Generate PSK credentials

```bash
export TRADFRI_GATEWAY_IP=192.168.x.x
export TRADFRI_SECURITY_CODE=xxxxxxxxxxxxxxxx   # printed on the gateway

uv run python scripts/gen_psk.py
# -> .tradfri_psk.json created
```

> Skip this step if you already have `.tradfri_psk.json`.
> For DTLS issues, see [`docs/dtls-tradfri-pitfalls.md`](docs/dtls-tradfri-pitfalls.md).

### 3. Scan devices

```bash
uv run python scripts/scan.py
# Output saved to devices.json; or use mcporter call tradfri.refresh_devices later
```

### 4. Configure

```bash
cp .env.example .env
# Edit .env — set TRADFRI_GATEWAY_IP
```

Edit `aliases.json` to define friendly names (supports four types):

```json
{
  "Living Room": {
    "type": "virtual",
    "groups": [131079],
    "devices": [65545, 65553, 65554, 65555]
  },
  "Bedroom": {"type": "group", "id": 131089},
  "Dining Track": {"type": "device_list", "ids": [65579, 65580, 65581]},
  "Desk Lamp": {"type": "device", "id": 65551}
}
```

| Type | Description |
|------|-------------|
| `virtual` | Virtual room: combine multiple IKEA groups + standalone devices |
| `group` | Native IKEA group |
| `device_list` | Collection of devices (when no IKEA group exists) |
| `device` | Single device |

### 5. Start (Docker)

```bash
docker compose up -d
docker compose logs -f   # verify DTLS handshake succeeds
```

### 6. Connect mcporter

```bash
npm install -g mcporter
mcporter config add tradfri --url http://localhost:8765/mcp
mcporter list tradfri   # verify tools appear
```

### 7. Test

```bash
mcporter call tradfri.list_aliases
mcporter call tradfri.control_by_name name="Living Room" state=false
mcporter call tradfri.control_by_name name="Living Room" state=true
mcporter call tradfri.set_color_temp name="Desk Lamp" direction=warm
```

---

## MCP Tools

| Tool | Description |
|------|-------------|
| `control_group` | Control a group (on/off, brightness) |
| `control_device` | Control a single device |
| `control_by_name` | **Most used** — control by alias name (all alias types) |
| `set_color_temp` | Adjust color temperature (`direction: warm/cool` or `mireds: 250-454`) |
| `set_color` | Set color (RGB bulbs: red/green/blue/orange/yellow/purple/pink) |
| `activate_scene` | Trigger a scene |
| `get_status` | Query real-time status (supports `name=`) |
| `list_devices` | List all devices, groups, scenes, and aliases |
| `list_aliases` | List alias names (lightweight, for LLM quick lookup) |
| `refresh_devices` | Re-scan gateway, update devices.json |
| `find_by_name` | Resolve name to ID |
| `send_notification` | Telegram push notification (silent no-op if unconfigured) |

---

## CoAP OBSERVE (Push Notifications)

On startup, the server subscribes to CoAP OBSERVE on every alias. When a light changes state (e.g. via physical remote or Apple Home), the server detects the change and sends a Telegram notification.

**Requirements:** Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`.

**Behavior:**
- Baseline state captured at startup
- Only notifies on **state changes** (not initial values)
- Auto-reconnects on OBSERVE subscription failure (retry interval: `TRADFRI_POLL_INTERVAL`, default 30s)
- Does not interfere with control operations (OBSERVE owns the CoAP context lifecycle)

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TRADFRI_GATEWAY_IP` | **Yes** | — | Gateway LAN IP |
| `MCP_PORT` | | `8765` | HTTP server port |
| `MCP_HOST` | | `0.0.0.0` | Bind address |
| `PSK_FILE` | | `.tradfri_psk.json` | PSK credentials path |
| `DEVICES_FILE` | | `devices.json` | Device cache path |
| `ALIASES_FILE` | | `aliases.json` | Alias mapping path |
| `TELEGRAM_BOT_TOKEN` | | — | Telegram Bot token (optional, for push notifications) |
| `TELEGRAM_CHAT_ID` | | — | Telegram Chat ID (optional) |
| `TRADFRI_POLL_INTERVAL` | | `30` | OBSERVE reconnect interval in seconds |

### Docker Log Rotation

Container logs auto-rotate (`max-size: 10m`, 3 files, 30MB cap). All MCP tool calls are logged (e.g. `control_by_name(name='Living Room', state=True)`) for debugging without unbounded growth.

---

## OpenClaw Integration

### How it works

OpenClaw doesn't have a `mcpServers` config (unlike Claude Desktop). Its MCP integration uses the **mcporter skill**: the AI agent calls `mcporter` CLI via the `exec` tool.

For smaller LLMs, complex mcporter syntax can be unreliable:

```bash
# Too complex for smaller models — multiple key=value params + different tool names
mcporter call tradfri.control_by_name name=Living\ Room state=true
mcporter call tradfri.set_color_temp name=Living\ Room direction=warm
```

The solution is a **wrapper script** that hides the complexity:

```bash
tradfri Living\ Room on
tradfri Living\ Room off
tradfri Living\ Room brightness 80    # percentage 0-100
tradfri Living\ Room colortemp warm
tradfri Desk\ Lamp color red          # RGB bulbs: red/green/blue/orange/yellow/purple/pink
tradfri status Living\ Room
tradfri list
```

### Installation

**Prerequisites:** mcporter installed and configured (see Quick Start step 6).

**1. Install OpenClaw skill**

```bash
# Copy to OpenClaw workspace (symlinks not supported — OpenClaw rejects cross-directory realPath)
cp -r openclaw-skill ~/.openclaw/workspace/skills/tradfri
```

**2. Install wrapper script**

```bash
ln -s $(pwd)/openclaw-skill/scripts/tradfri /opt/homebrew/bin/tradfri
# Linux: ln -s $(pwd)/openclaw-skill/scripts/tradfri /usr/local/bin/tradfri
```

**3. Add instructions to AGENTS.md**

Add to `~/.openclaw/workspace/AGENTS.md` (**not** systemPrompt, **not** SKILL.md):

```markdown
## IKEA TRADFRI Light Control

When asked to control lights -> exec `tradfri` command immediately, no explanation needed.

tradfri Living\ Room on
tradfri Living\ Room off
tradfri Living\ Room brightness 80
tradfri Desk\ Lamp colortemp warm
tradfri Desk\ Lamp color red
tradfri status Desk\ Lamp
tradfri list
```

> **Important:** Only AGENTS.md content is fully injected into the LLM context. systemPrompt and SKILL.md are not reliably included.

**4. Restart OpenClaw gateway**

```bash
launchctl kickstart -k gui/$(id -u)/ai.openclaw.gateway
```

**5. Test**

Tell OpenClaw via Telegram: "turn on the living room lights" and verify.

---

## Pitfalls

### Docker `network_mode: host` doesn't work on macOS

macOS Docker runs inside a LinuxKit VM. `network_mode: host` only exposes the VM's network, not the Mac's LAN.

**Solution:** Use default bridge network + `ports` mapping. The bridge network can reach LAN IPs (including gateway UDP 5684) through VM NAT. Works on both macOS and Linux.

```yaml
# docker-compose.yml
services:
  tradfri-mcp:
    ports:
      - "8765:8765"     # do NOT use network_mode: host
```

### CoAP context ownership: OBSERVE owns the reset

Originally `coap_put` / `coap_get` would reset the CoAP context on failure (`_ctx = None`). This breaks active OBSERVE sessions because the TRADFRI gateway allows only one DTLS session per PSK identity.

**Correct approach:**
- `coap_put` / `coap_get` on failure: **do not reset context**, just raise
- OBSERVE task detects disconnection, then calls `reset_ctx()` to clear stale context
- Next `get_ctx()` automatically creates a new DTLS session

### OBSERVE doesn't need semaphore serialization

Attempted `asyncio.Semaphore(1)` + 2s delay to serialize OBSERVE init, thinking 20 concurrent GETs would overwhelm the gateway. Testing proved otherwise — the gateway handles concurrent OBSERVE GETs fine. The root cause was the context reset bug above, not concurrency.

Removing the semaphore reduced OBSERVE init time from ~40s to a few seconds.

### OpenClaw skill can't use symlinks

If `~/.openclaw/workspace/skills/tradfri` is a symlink, OpenClaw rejects it: `Skipping skill path that resolves outside its configured root.` Must use `cp -r`.

### Only AGENTS.md is fully injected into LLM context

`openclaw.json`'s `systemPrompt` is appended at the end of the system prompt and easily truncated. `SKILL.md` only has name/description referenced, not content. Only `AGENTS.md` content fully appears in the LLM's system prompt.

### `_comment` in aliases.json crashes list_devices

A `"_comment": "..."` string entry in `aliases.json` causes `target.get("type")` to crash. Fix: skip non-dict entries.

---

## Troubleshooting

| Error | Solution |
|-------|----------|
| `CredentialsMissingError` | Remove `:5684` from credentials URI — see [`dtls-tradfri-pitfalls.md` #9](docs/dtls-tradfri-pitfalls.md) |
| DTLS handshake failure | TinyDTLS C source needs patching — see [`dtls-tradfri-pitfalls.md` #6 #7](docs/dtls-tradfri-pitfalls.md) |
| `NetworkError` loop | Ensure `coap_client.py`'s `coap_put`/`coap_get` don't set `_ctx = None` (see pitfalls above) |
| Device not found | `mcporter call tradfri.refresh_devices` or `uv run python scripts/scan.py` |
| mcporter can't connect | `docker compose ps` to verify container, `curl http://localhost:8765/mcp` to verify HTTP |
| Docker container can't reach gateway | macOS doesn't support `network_mode: host`; use bridge + `ports` (see pitfalls above) |

---

## Development (without Docker)

```bash
TRADFRI_GATEWAY_IP=192.168.x.x uv run python server.py

# MCP Inspector (Web UI)
npx @modelcontextprotocol/inspector http://localhost:8765/mcp
# -> http://localhost:6274
```


