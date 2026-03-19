# "Turn on the living room lights" -- A TRADFRI MCP That Actually Listens

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![FastMCP](https://img.shields.io/badge/FastMCP-3.x-orange.svg)](https://github.com/jlowin/fastmcp)
[![MCP](https://img.shields.io/badge/Protocol-MCP-purple.svg)](https://modelcontextprotocol.io)

[正體中文](README_zh.md)

An MCP Server for the IKEA TRADFRI smart home gateway. Because apparently the only way to talk to a Swedish light bulb is through CoAP-over-DTLS, this project wraps all that ceremony into MCP tools so AI assistants can control your lights, plugs, and scenes with plain English. No PhD in IoT protocols required (though it certainly helped writing this).

> **Full tutorial (a.k.a. the war diary)**: [`docs/openclaw-tradfri-mcp-tutorial.md`](docs/openclaw-tradfri-mcp-tutorial.md)
> **DTLS pitfalls on macOS (a.k.a. "why is nothing working")**: [`docs/dtls-tradfri-pitfalls.md`](docs/dtls-tradfri-pitfalls.md)

---

## How This Whole Thing Hangs Together

```
User (Telegram / Web UI)
  -> AI Agent (OpenClaw / Claude Desktop / etc.)
  -> mcporter CLI (MCP client)
  -> tradfri-mcp (Docker, FastMCP HTTP server, port 8765)
  -> aiocoap (CoAP over DTLS)
  -> TRADFRI gateway (LAN, UDP 5684)
  -> Zigbee -> Lights / Plugs
```

## What It Actually Does

- **Natural language control** -- "turn on the living room lights" just works, which still feels like magic every time
- **12 MCP tools** -- on/off, brightness, color temp, color, scenes, status, and more than you probably need
- **Alias system** -- map friendly names to devices, groups, or virtual rooms, because nobody wants to memorize device ID 65553
- **CoAP OBSERVE push notifications** -- get notified via Telegram when lights change (e.g. via remote or Apple Home), so you can feel surveilled by your own house
- **Docker-ready** -- `docker compose up -d` with log rotation, like a responsible adult
- **Vendored TinyDTLS** -- patched for macOS; no OpenSSL 3 dependency, because that road leads only to tears

## What Lives Where

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

## Quick Start (The Optimistic Version)

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
> For DTLS issues, see [`docs/dtls-tradfri-pitfalls.md`](docs/dtls-tradfri-pitfalls.md). You'll probably need it.

### 3. Scan devices

```bash
uv run python scripts/scan.py
# Output saved to devices.json; or use mcporter call tradfri.refresh_devices later
```

### 4. Configure (the easy part, for once)

```bash
cp .env.example .env
# Edit .env — set TRADFRI_GATEWAY_IP
```

Edit `aliases.json` to define friendly names. Four types are supported, because one type would have been too simple:

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

### 5. Fire it up (Docker)

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

### 7. The moment of truth

```bash
mcporter call tradfri.list_aliases
mcporter call tradfri.control_by_name name="Living Room" state=false
mcporter call tradfri.control_by_name name="Living Room" state=true
mcporter call tradfri.set_color_temp name="Desk Lamp" direction=warm
```

---

## MCP Tools (Your New Remote Control)

| Tool | Description |
|------|-------------|
| `control_group` | Control a group (on/off, brightness) |
| `control_device` | Control a single device |
| `control_by_name` | **Most used** -- control by alias name (all alias types) |
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

## CoAP OBSERVE (a.k.a. Your House Tattles on Itself)

On startup, the server subscribes to CoAP OBSERVE on every alias. When a light changes state -- say, someone uses the physical remote or Apple Home -- the server catches it and fires off a Telegram notification. Yes, you will now get a push notification when your partner turns on the bathroom light. You've been warned.

**Requirements:** Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`.

**How it behaves:**
- Captures baseline state at startup
- Only notifies on **state changes** (not initial values, thankfully)
- Auto-reconnects on OBSERVE subscription failure (retry interval: `TRADFRI_POLL_INTERVAL`, default 30s)
- Does not interfere with control operations (OBSERVE owns the CoAP context lifecycle, and we learned the hard way why that matters)

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TRADFRI_GATEWAY_IP` | **Yes** | -- | Gateway LAN IP |
| `MCP_PORT` | | `8765` | HTTP server port |
| `MCP_HOST` | | `0.0.0.0` | Bind address |
| `PSK_FILE` | | `.tradfri_psk.json` | PSK credentials path |
| `DEVICES_FILE` | | `devices.json` | Device cache path |
| `ALIASES_FILE` | | `aliases.json` | Alias mapping path |
| `TELEGRAM_BOT_TOKEN` | | -- | Telegram Bot token (optional, for push notifications) |
| `TELEGRAM_CHAT_ID` | | -- | Telegram Chat ID (optional) |
| `TRADFRI_POLL_INTERVAL` | | `30` | OBSERVE reconnect interval in seconds |

### Docker Log Rotation (Because Logs Grow Like Weeds)

Container logs auto-rotate (`max-size: 10m`, 3 files, 30MB cap). All MCP tool calls are logged (e.g. `control_by_name(name='Living Room', state=True)`) for debugging without unbounded growth. Your future self will thank you.

---

## OpenClaw Integration (Where It Gets Interesting)

### How it works

OpenClaw doesn't have a `mcpServers` config (unlike Claude Desktop -- wouldn't that have been nice). Its MCP integration uses the **mcporter skill**: the AI agent calls `mcporter` CLI via the `exec` tool.

Here's the problem: for smaller LLMs, complex mcporter syntax is about as reliable as a chocolate teapot:

```bash
# Too complex for smaller models — multiple key=value params + different tool names
mcporter call tradfri.control_by_name name=Living\ Room state=true
mcporter call tradfri.set_color_temp name=Living\ Room direction=warm
```

The solution is a **wrapper script** that hides all the gnarly bits:

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

Add to `~/.openclaw/workspace/AGENTS.md` (**not** systemPrompt, **not** SKILL.md -- trust me on this one):

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

> **Important:** Only AGENTS.md content is fully injected into the LLM context. systemPrompt and SKILL.md are not reliably included. Learned that one the hard way.

**4. Restart OpenClaw gateway**

```bash
launchctl kickstart -k gui/$(id -u)/ai.openclaw.gateway
```

**5. Test**

Tell OpenClaw via Telegram: "turn on the living room lights" and bask in the glow of success (literally).

---

## Pitfalls (So You Don't Have To)

### Docker `network_mode: host` doesn't work on macOS

macOS Docker runs inside a LinuxKit VM. `network_mode: host` only exposes the VM's network, not the Mac's LAN. This is one of those things that works perfectly on Linux and then laughs at you on macOS.

**Solution:** Use default bridge network + `ports` mapping. The bridge network can reach LAN IPs (including gateway UDP 5684) through VM NAT. Works on both macOS and Linux. Boring, but correct.

```yaml
# docker-compose.yml
services:
  tradfri-mcp:
    ports:
      - "8765:8765"     # do NOT use network_mode: host
```

### CoAP context ownership: OBSERVE owns the reset

Originally `coap_put` / `coap_get` would reset the CoAP context on failure (`_ctx = None`). Sounds reasonable, right? Except it destroys active OBSERVE sessions because the TRADFRI gateway allows only one DTLS session per PSK identity. Oops.

**Correct approach (after learning the hard way):**
- `coap_put` / `coap_get` on failure: **do not reset context**, just raise
- OBSERVE task detects disconnection, then calls `reset_ctx()` to clear stale context
- Next `get_ctx()` automatically creates a new DTLS session

### OBSERVE doesn't need semaphore serialization

I attempted `asyncio.Semaphore(1)` + 2s delay to serialize OBSERVE init, thinking 20 concurrent GETs would overwhelm the gateway. Pride comes before the fall -- testing proved the gateway handles concurrent OBSERVE GETs just fine. The root cause was the context reset bug above, not concurrency.

Removing the semaphore reduced OBSERVE init time from ~40s to a few seconds. Sometimes the best optimization is deleting your own clever code.

### OpenClaw skill can't use symlinks

If `~/.openclaw/workspace/skills/tradfri` is a symlink, OpenClaw rejects it: `Skipping skill path that resolves outside its configured root.` Must use `cp -r`. Not the hill I chose to die on.

### Only AGENTS.md is fully injected into LLM context

`openclaw.json`'s `systemPrompt` is appended at the end of the system prompt and easily truncated. `SKILL.md` only has name/description referenced, not content. Only `AGENTS.md` content fully appears in the LLM's system prompt. I spent an embarrassing amount of time debugging this before figuring it out.

### `_comment` in aliases.json crashes list_devices

A `"_comment": "..."` string entry in `aliases.json` causes `target.get("type")` to crash. Fix: skip non-dict entries. The kind of bug that takes 2 seconds to fix and 2 hours to find.

---

## Troubleshooting (The "Why Isn't It Working" Section)

| Error | Solution |
|-------|----------|
| `CredentialsMissingError` | Remove `:5684` from credentials URI -- see [`dtls-tradfri-pitfalls.md` #9](docs/dtls-tradfri-pitfalls.md) |
| DTLS handshake failure | TinyDTLS C source needs patching -- see [`dtls-tradfri-pitfalls.md` #6 #7](docs/dtls-tradfri-pitfalls.md) |
| `NetworkError` loop | Ensure `coap_client.py`'s `coap_put`/`coap_get` don't set `_ctx = None` (see pitfalls above) |
| Device not found | `mcporter call tradfri.refresh_devices` or `uv run python scripts/scan.py` |
| mcporter can't connect | `docker compose ps` to verify container, `curl http://localhost:8765/mcp` to verify HTTP |
| Docker container can't reach gateway | macOS doesn't support `network_mode: host`; use bridge + `ports` (see pitfalls above) |

---

## Development (Living Dangerously Without Docker)

```bash
TRADFRI_GATEWAY_IP=192.168.x.x uv run python server.py

# MCP Inspector (Web UI)
npx @modelcontextprotocol/inspector http://localhost:8765/mcp
# -> http://localhost:6274
```

---

## Related Projects (More Things I Built)

- [kc_openclaw_local_llm](https://github.com/KerberosClaw/kc_openclaw_local_llm) -- OpenClaw + Local LLM: What Actually Works
- [kc_ai_skills](https://github.com/KerberosClaw/kc_ai_skills) -- AI Skills That Actually Do Things
