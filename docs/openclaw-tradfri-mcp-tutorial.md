# Building a Custom MCP Server with OpenClaw: IKEA TRADFRI Smart Home Integration (Pitfalls and All)

This document is a complete record of building a custom MCP Server on macOS, connecting it to an IKEA TRADFRI smart home gateway, and integrating it with the OpenClaw AI assistant so that natural language commands control lights, sockets, and scenes. If this sounds straightforward, congratulations — you've already been misled.

**By the end of this document you will be able to:**
- Tell an AI "dim the living room a bit" and watch it actually happen (every success deserves a screenshot)
- Understand why "just install the lib and run it" is completely impossible on this path
- Build a reusable MCP server development and integration pattern

**This is not a translation of official docs — it's a record of pitfalls.** Official docs tell you what to do; this document tells you why that won't work.

---

## Environment

| Component | Spec |
|-----------|------|
| Host | Mac Mini (Apple Silicon, macOS 15) |
| AI platform | [OpenClaw](https://openclaw.ai) 2026.3.x |
| Smart home | IKEA TRADFRI gateway E1526, firmware 1.21.x |
| Protocol | CoAP over DTLS (CoAPS), port 5684 |
| MCP framework | [FastMCP](https://github.com/jlowin/fastmcp) 3.x |
| Container | Docker (persistent service on Mac Mini) |

---

## Chapter 1: Why this path feels like walking through thorns

### TRADFRI is not the kind of API you're thinking of

The IKEA TRADFRI gateway does not provide a REST API. No `curl`, no JSON over HTTP, nothing like that. It uses:

- **CoAP** (Constrained Application Protocol): the HTTP of the IoT world, but over UDP, with sparse documentation
- **DTLS 1.2** (Datagram TLS): CoAP's encryption layer, equivalent to TLS over UDP — debugging difficulty doubled
- **PSK cipher**: `TLS_PSK_WITH_AES_128_CCM_8`, not supported by OpenSSL 3.x. Yes, you read that right.

This means you cannot connect to it with `requests`, `httpx`, or even `aiohttp`. You need a CoAP client that implements DTLS + AES-CCM. Just understanding this took me an afternoon.

### State of existing libraries ("great expectations, harsh reality")

| Library | Problem |
|---------|---------|
| `pytradfri` (official Python SDK) | Internally uses `aiocoap`, whose tinydtls transport has a socket issue on macOS |
| `aiocoap` (default libcoap backend) | OpenSSL 3 doesn't support AES-CCM; handshake fails immediately |
| `DTLSSocket 0.2.3` (TinyDTLS wrapper) | Has multiple bugs requiring patches to TinyDTLS C source to work on macOS |

The complete DTLS pitfall record and fixes are in [`docs/dtls-tradfri-pitfalls.md`](./dtls-tradfri-pitfalls.md). This document won't repeat that pain.

**Conclusion: once the DTLS layer was working, drop `pytradfri`'s model layer (incompatible with gateway firmware), use `aiocoap` to send CoAP requests directly, and parse JSON manually.** Sometimes the best framework is no framework.

---

## Chapter 2: Architecture design ("why so many layers?")

### Overall architecture

```
User (Telegram message)
  ↓
OpenClaw (Mac Mini persistent process, AI agent)
  ↓  mcporter skill (OpenClaw built-in)
mcporter CLI (MCP client)
  ↓  HTTP (localhost:8765)
tradfri-mcp (Docker container, FastMCP HTTP server)
  ↓  CoAPS (aiocoap)
TRADFRI gateway (192.168.x.x:5684)
  ↓  Zigbee
lights, sockets, remotes
```

### Why this architecture (every choice has a story)

**Why not pytradfri?**

The latest pytradfri version assumes the gateway returns fields `15025`, `15015`, etc. in its pydantic models, but firmware 1.21.x doesn't return these fields, causing a `ValidationError` on every call. Patching it costs more than just implementing directly. Sometimes "official SDK" is a trap.

**Why mcporter instead of editing OpenClaw config directly?**

OpenClaw doesn't have an `mcpServers` config field (unlike Claude Desktop). Its MCP integration goes through the **mcporter skill**: OpenClaw's AI agent calls MCP tools by running the `mcporter` CLI. This is OpenClaw's officially recommended third-party MCP integration method. Not my choice, but it works.

**Why Docker?**

`tradfri-mcp` needs to:
1. Run persistently (maintain the aiocoap event loop)
2. Be decoupled from OpenClaw (independent upgrades, restarts, no interference)
3. Be managed as a service on Mac Mini

Docker + `restart: unless-stopped` is the cleanest option. Sometimes the boring technology choice is the best one.

**Why HTTP transport instead of stdio?**

stdio transport starts a new subprocess for every tool call. A persistent aiocoap event loop cannot survive in stdio mode. HTTP transport lets the Docker container run continuously; mcporter connects via HTTP. Between process-per-call and long-lived-connection in an IoT scenario, there's really no choice.

---

## Chapter 3: MCP Server design (finally getting to the point)

### Technology choice: FastMCP 3.x

FastMCP is currently the most widely used Python MCP server framework — it eliminates a lot of boilerplate:

- FastMCP 1.0 was merged into the official Python MCP SDK
- FastMCP 3.x continues as an independent project with millions of daily downloads
- Automatically generates MCP tool schemas from type hints + docstrings

```python
from fastmcp import FastMCP

mcp = FastMCP("tradfri")

@mcp.tool()
async def control_group(group_id: int, brightness: int) -> str:
    """Control group brightness (0–254). For a whole room of lights."""
    await coap_put(f"/15004/{group_id}", {"5851": brightness})
    return f"group {group_id} brightness set to {brightness}"
```

### Device topology management (the translation layer between human language and machine language)

Devices on the gateway are identified by numeric IDs, but the AI needs to know "living room = group_id X". Nobody says "turn on 65553."

**Approach: `devices.json` + `aliases.json`**

```jsonc
// devices.json (auto-generated by scripts/scan.py, not manually maintained)
{
  "groups": [
    {"id": 131079, "name": "GU10 warm white", "state": true, "brightness": 200}
  ],
  "devices": [...]
}

// aliases.json (manually maintained by user)
{
  // virtual room (combines multiple IKEA groups + individual devices)
  "living_room": {
    "type": "virtual",
    "groups": [131079],
    "devices": [65545, 65553, 65554, 65555, 65556, 65572, 65573, 65574]
  },
  // native IKEA group
  "master_bedroom": {"type": "group", "id": 131089},
  // device list (when there's no IKEA group)
  "dining_track_lights": {"type": "device_list", "ids": [65579, 65580, 65581]},
  // single device
  "dining_table_lamp": {"type": "device", "id": 65551}
}
```

**Why does the `virtual` type exist? (another "why did IKEA design it this way?" story)**

IKEA TRADFRI groups are organised by bulb model ("GU10 warm white", "GU10 colour"), not by room. Apple Home organises by room. If your living room has GU10 warm white bulbs, GU10 colour bulbs, and E27 bulbs, IKEA has put them in three separate groups. The `virtual` type lets you combine cross-IKEA-group devices into a logical "room"; `control_by_name` automatically expands it and controls all targets in sequence.

### MCP Tools overview

| Tool | Description |
|------|-------------|
| `control_group` | Control an entire group (on/off, brightness) |
| `control_device` | Control a single device |
| `control_by_name` | Control by alias name (supports virtual/device_list/group/device) |
| `set_color_temp` | Adjust colour temperature (warm/cool) |
| `set_color` | Set colour (red/green/blue/orange/yellow...) |
| `activate_scene` | Activate a scene |
| `get_status` | Query current device or group state |
| `list_devices` | List all devices/groups (with aliases) |
| `list_aliases` | List all alias names and types (lightweight, for LLM quick-lookup) |
| `refresh_devices` | Re-scan gateway, update devices.json |
| `find_by_name` | Find device/group ID by name |

### Colour temperature and colour support (the physics behind the numbers)

**Colour temperature (white light)**

CoAP key `5711` is in **Mireds**, not Kelvin. Why not Kelvin, which everyone understands? Because this is IoT — making things inconvenient is a core feature:

```
Mireds = 1,000,000 / Kelvin
```

| Mireds | Kelvin | Feel |
|--------|--------|------|
| 250 | 4000K | Cool white / daylight |
| 370 | 2700K | Warm white / yellow |
| 454 | 2200K | Very warm / candlelight |

"Warmer" = `mireds + 50`, "cooler" = `mireds - 50`, clamped to 250–454.

**Colour (colour bulbs)**

CoAP keys `5709` (X) and `5710` (Y), range 0–65535:

| Colour | X | Y |
|--------|---|---|
| red | 45914 | 19661 |
| green | 19661 | 45914 |
| blue | 9830 | 3932 |
| orange | 42163 | 25887 |
| yellow | 37449 | 37449 |
| warm_white | 30140 | 26870 |

---

## Chapter 4: OpenClaw integration (the art of wiring everything together)

### Install mcporter

OpenClaw ships with a built-in mcporter skill (`/opt/homebrew/lib/node_modules/openclaw/skills/mcporter/`), but requires the corresponding binary:

```bash
# Option 1: click Install from the Skills page in the OpenClaw dashboard
# Option 2: manual
npm install -g mcporter
```

After installation, `openclaw skills check` should show `✓ ready   📦 mcporter`.

### Configure mcporter to point at tradfri-mcp

```bash
mcporter config add tradfri --url http://localhost:8765/mcp
```

Verify (deep breath, then...):

```bash
mcporter list tradfri
# → lists control_group, control_device, control_by_name, ...

mcporter call tradfri.control_by_name name=living_room brightness=80
# → living room lights dim
```

> **Note**: the mcporter flag is `--url`, not `--http-url`. Ask me how I know.

### Create a tradfri OpenClaw skill (give the AI a manual)

An OpenClaw skill is a SKILL.md file. When the user says something matching the skill's triggers, OpenClaw injects SKILL.md into the LLM's context so it knows how to call mcporter.

This is cleaner than dumping all light aliases into the system prompt — the skill only loads when needed. Beautiful in theory; see the pitfalls section for reality.

Create the directory and files:

```bash
mkdir -p ~/.openclaw/workspace/skills/tradfri/.clawhub
```

`~/.openclaw/workspace/skills/tradfri/SKILL.md`:

```markdown
---
name: tradfri
description: IKEA TRADFRI smart home control — control lights, sockets, and scenes via mcporter
author: local
version: 1.0.0
triggers:
  - "turn on"
  - "turn off"
  - "dim"
  - "brighten"
  - "colour temp"
  - "tradfri"
  - "IKEA"
  - "lights"
---

# IKEA TRADFRI smart home control

## How to use

1. Call `mcporter call tradfri.list_aliases` to get the list of available names
2. Choose the correct name from the list and call the appropriate tool

## Available tools

### On/off / brightness
mcporter call tradfri.control_by_name name=<name> state=true/false
mcporter call tradfri.control_by_name name=<name> brightness=<0-254>

### Colour temperature
mcporter call tradfri.set_color_temp name=<name> direction=warm/cool

### Colour (RGB bulbs only)
mcporter call tradfri.set_color name=<name> color=red/green/blue/orange/yellow

### Query
mcporter call tradfri.get_status name=<name>
```

`~/.openclaw/workspace/skills/tradfri/_meta.json`:

```json
{
  "slug": "tradfri",
  "version": "1.0.0",
  "description": "IKEA TRADFRI smart home light control"
}
```

`~/.openclaw/workspace/skills/tradfri/.clawhub/origin.json`:

```json
{
  "version": 1,
  "registry": "local",
  "slug": "tradfri",
  "installedVersion": "1.0.0",
  "installedAt": 1773986800000
}
```

After restarting the OpenClaw gateway, `openclaw skills list` should show the tradfri skill (`✓ ready`, source: `openclaw-workspace`):

```bash
launchctl unload ~/Library/LaunchAgents/ai.openclaw.gateway.plist
launchctl load  ~/Library/LaunchAgents/ai.openclaw.gateway.plist
openclaw skills list | grep tradfri
# ✓ ready   📦 tradfri   IKEA TRADFRI smart home...   openclaw-workspace
```

### OpenClaw Gateway HTTP API (for development, not required)

OpenClaw gateway listens on `127.0.0.1:18789` by default. To call it from an external program (e.g. Claude Code's openclaw-mcp), enable the HTTP API:

Add to `~/.openclaw/openclaw.json`:

```json
{
  "gateway": {
    "http": {
      "endpoints": {
        "chatCompletions": {
          "enabled": true
        }
      }
    }
  }
}
```

After restarting the gateway, `POST http://127.0.0.1:18789/v1/chat/completions` is available.

### Integration test tool: openclaw-mcp (for developers who don't want to switch to Telegram)

Install [freema/openclaw-mcp](https://github.com/freema/openclaw-mcp) as a Claude Code MCP server so Claude Code can send messages directly to OpenClaw without going through Telegram:

```bash
claude mcp add openclaw npx openclaw-mcp \
  -e OPENCLAW_URL=http://127.0.0.1:18789 \
  -e OPENCLAW_GATEWAY_TOKEN=<your-token> \
  -e OPENCLAW_TIMEOUT_MS=300000
```

The token is in `gateway.auth.token` in `~/.openclaw/openclaw.json`.

---

## Chapter 5: Testing strategy ("how to confirm the light actually turned on")

### Phase 1: MCP server standalone testing (no OpenClaw / Ollama needed)

**Direct mcporter calls (fastest smoke test):**

```bash
# confirm tools are correctly defined
mcporter list tradfri

# test control
mcporter call tradfri.list_aliases
mcporter call tradfri.control_by_name name=living_room brightness=50
mcporter call tradfri.set_color_temp name=dining_table_lamp direction=warm
mcporter call tradfri.activate_scene group_id=131073 scene_id=196608

# query state
mcporter call tradfri.get_status name=living_room
```

**MCP Inspector (web UI, more user-friendly):**

```bash
npx @modelcontextprotocol/inspector http://localhost:8765/mcp
```

Open `http://localhost:6274` to list tools, make calls, and inspect request/response in a browser. No code required.

### Phase 2: OpenClaw integration testing (requires Ollama running)

**Via Telegram:**

Use the normal user flow and observe whether OpenClaw correctly invokes mcporter. Then watch the living room lights respond and feel the satisfaction of having built something that actually works.

---

## Chapter 6: Deployment ("making something that probably won't break")

### Directory structure

```
tradfri_mcp/
├── server.py              # FastMCP server main entry point
├── aliases.json           # user-defined aliases (including virtual rooms)
├── devices.json           # device list (generated by scan, .gitignore)
├── .tradfri_psk.json      # PSK credentials (.gitignore)
├── .env                   # environment variables (.gitignore)
├── .env.example           # template
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── README.md
├── scripts/
│   ├── scan.py            # scan gateway devices
│   └── gen_psk.py         # generate PSK credentials
└── docs/
    ├── dtls-tradfri-pitfalls.md
    └── openclaw-tradfri-mcp-tutorial.md  ← this file
```

### Docker Compose

```yaml
services:
  tradfri-mcp:
    image: tradfri-mcp:latest
    build: .
    ports:
      - "8765:8765"
    volumes:
      - ./devices.json:/app/devices.json
      - ./aliases.json:/app/aliases.json
      - ./.tradfri_psk.json:/app/.tradfri_psk.json:ro
    environment:
      - TRADFRI_GATEWAY_IP=${TRADFRI_GATEWAY_IP}
      - MCP_PORT=8765
    network_mode: host
    restart: unless-stopped
```

### Environment variables

```bash
# .env (not committed to git)
TRADFRI_GATEWAY_IP=192.168.x.x
```

PSK identity and key are stored in `.tradfri_psk.json` (mounted into the container, not baked into the image). Secrets belong in secret places.

---

## Appendix A: PSK generation (getting your entry pass)

Before first use, request a PSK from the gateway (exchange the security code for a long-term credential). Think of it as trading a temporary visitor pass for a permanent employee badge:

```bash
export TRADFRI_GATEWAY_IP=192.168.x.x
export TRADFRI_SECURITY_CODE=xxxxxxxxxxxxxxxx   # code on the back of the gateway

uv run python scripts/gen_psk.py
# ✓ DTLS handshake complete, gateway firmware: 1.21.xxxx
# ✓ PSK saved to .tradfri_psk.json
#   identity: tradfri-xxxxxxxx
#   psk:      xxxx****
```

Implementation details of `gen_psk.py` (DTLS + CoAP POST) are in [`docs/dtls-tradfri-pitfalls.md`](./dtls-tradfri-pitfalls.md).

---

## Appendix B: Device scan (getting to know what's in your home)

```bash
export TRADFRI_GATEWAY_IP=192.168.x.x
uv run python scripts/scan.py
# → outputs JSON for all devices, groups, and scenes
# → copy to devices.json
```

Recommended: run once manually on first deployment, then use the `refresh_devices` MCP tool to update. Takes about three seconds — faster than walking to a light switch.

---

## Appendix C: TRADFRI CoAP quick reference (the cheat sheet)

### Resource paths

| Path | Description |
|------|-------------|
| `GET /15001` | list all device IDs |
| `GET /15001/{id}` | single device details |
| `PUT /15001/{id}` | control a single device |
| `GET /15004` | list all group IDs |
| `GET /15004/{id}` | single group details |
| `PUT /15004/{id}` | control a group |
| `GET /15005/{gid}` | scene list for a group |
| `GET /15005/{gid}/{sid}` | scene details |

### Common CoAP keys (these numbers will be burned into your brain)

| Key | Meaning | Range |
|-----|---------|-------|
| `9001` | name | string |
| `9003` | ID | integer |
| `5750` | device type | 0=remote, 2=light, 3=socket |
| `5850` | on/off state | 0/1 |
| `5851` | brightness | 0–254 |
| `5711` | colour temp (Mireds) | 250–454 |
| `5709` | colour X (CIE) | 0–65535 |
| `5710` | colour Y (CIE) | 0–65535 |
| `9039` | trigger scene ID | integer |

### aiocoap credentials configuration (important — I already stepped in this one for you)

Do not include a port in the URI pattern:

```python
ctx.client_credentials.load_from_dict({
    "coaps://192.168.x.x/*": {      # ← do NOT write :5684
        "dtls": {
            "psk": psk.encode(),
            "client-identity": identity.encode(),
        }
    }
})
```

---

*MCP server source code for this document: [tradfri_mcp](https://github.com/marcinn2/tradfri_mcp)*
*Detailed DTLS pitfall record: [docs/dtls-tradfri-pitfalls.md](./dtls-tradfri-pitfalls.md)*
