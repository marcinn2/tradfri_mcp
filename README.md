# "Turn on the living room lights" -- A TRADFRI MCP That Actually Listens

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![FastMCP](https://img.shields.io/badge/FastMCP-3.x-orange.svg)](https://github.com/jlowin/fastmcp)
[![MCP](https://img.shields.io/badge/Protocol-MCP-purple.svg)](https://modelcontextprotocol.io)

[Traditional Chinese](README_zh.md)

An MCP Server for the IKEA TRADFRI smart home gateway. Because apparently the only way to talk to a Swedish light bulb is through CoAP-over-DTLS, this project wraps all that ceremony into MCP tools so AI assistants can control your lights, plugs, and scenes with plain English. No PhD in IoT protocols required (though it certainly helped writing this).

> **Full tutorial (a.k.a. the war diary)**: [`docs/openclaw-tradfri-mcp-tutorial.md`](docs/openclaw-tradfri-mcp-tutorial.md)
> **DTLS pitfalls on macOS (a.k.a. "why is nothing working")**: [`docs/dtls-tradfri-pitfalls.md`](docs/dtls-tradfri-pitfalls.md)

---

## How This Whole Thing Hangs Together

```
User (Web UI / Telegram / voice)
  -> AI Agent (OpenClaw / Claude Desktop / etc.)
  -> mcporter CLI (MCP client)
  -> tradfri-mcp (Docker, FastMCP HTTP server, port 8765)
  -> aiocoap (CoAP over DTLS)
  -> TRADFRI gateway (LAN, UDP 5684)
  -> Zigbee -> Lights / Plugs
```

## What It Actually Does

- **Natural language control** -- "turn on the living room lights" just works, which still feels like magic every time
- **12 MCP tools** -- on/off, brightness, color temp, color, scenes, status, battery, device discovery, and more than you probably need
- **Alias system** -- map friendly names to devices, groups, or virtual rooms, because nobody wants to memorize device ID 65553
- **Pure TRADFRI/CoAP** -- talks directly to the gateway, no external services required
- **Docker-ready** -- `docker compose up -d` with log rotation, like a responsible adult
- **Vendored TinyDTLS** -- patched for macOS; no OpenSSL 3 dependency, because that road leads only to tears

## What Lives Where

```
tradfri_mcp/
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

> **Security Notice:** This project is designed for trusted home LAN environments. The MCP server does not implement TLS. With the default `0.0.0.0` bind it **requires** a bearer token via `MCP_AUTH_TOKEN` and refuses to start without one (see [Bearer Authentication](#bearer-authentication)) — but without TLS that token travels in plaintext. Do not expose the service port to the public internet without a TLS-terminating reverse proxy in front.

## Quick Start (The Optimistic Version)

### 1. Clone and install dependencies

```bash
git clone https://github.com/marcinn2/tradfri_mcp.git
cd tradfri_mcp
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
# and set MCP_AUTH_TOKEN to any secret string
```

The server binds to `0.0.0.0` (reachable from your LAN), so it **requires `MCP_AUTH_TOKEN`** and won't start without it. Pick any hard-to-guess string — you'll pass the same value to your MCP client in step 6. (Running only on this host? Set `MCP_HOST=127.0.0.1` instead and you can skip the token.)

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
mcporter config add tradfri --url http://localhost:8765/mcp --header "Authorization: Bearer your-secret-token-here"
mcporter list tradfri   # verify tools appear
```

Use the same value you set for `MCP_AUTH_TOKEN`. (If you bound to `127.0.0.1` without a token, drop the `--header` flag.)

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
| `battery_report` | List battery levels of remotes/sensors/blinds, lowest first (`threshold=` to filter, `live=true` to re-query) |
| `list_devices` | List all devices, groups, scenes, and aliases |
| `list_aliases` | List alias names (lightweight, for LLM quick lookup) |
| `refresh_devices` | Re-scan gateway, update devices.json |
| `find_by_name` | Resolve name to ID |

---

## Prompts (One-Tap Routines)

The server also ships reusable **MCP prompts** -- templated routines your client can surface as slash-commands or quick actions. They don't touch the gateway directly; each one hands the assistant a plan that drives the tools above, so you still see what's about to change.

| Prompt | Arguments | What it does |
|--------|-----------|--------------|
| `movie_night` | `room` (default `Living Room`) | Dim + warm for watching a film |
| `good_morning` | `room` (default `Bedroom`) | Full brightness, cool white to wake up |
| `good_night` | `keep_on` (optional) | Turn everything off; optionally leave one room dim |
| `set_mood` | `room`, `mood` | Interpret a mood (cozy/focus/party/relax...) into brightness/temp/colour |
| `battery_check` | -- | Report battery devices, flag anything low |

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
| `MCP_AUTH_TOKEN` | | -- | Bearer token for HTTP auth (disabled if unset) |
| `MCP_ALLOW_INSECURE` | | `false` | Allow a non-loopback bind with no auth token (trusted LAN override) |

### Bearer Authentication

The server binds to `0.0.0.0` by default (so it's reachable from other hosts / Docker). Because that exposes home control and device names to anyone on the network, **the server refuses to start on a non-loopback bind unless you either set a token or explicitly opt out.** On startup it checks:

- `MCP_AUTH_TOKEN` is set → starts with auth required ✅ (recommended)
- `MCP_HOST=127.0.0.1` → starts (only reachable from this host) ✅
- neither, and `MCP_ALLOW_INSECURE=1` → starts with a loud warning ⚠️ (trusted LAN only)
- neither, no override → **refuses to start** with instructions ❌

To require a bearer token, set `MCP_AUTH_TOKEN` in `.env`:

```bash
MCP_AUTH_TOKEN=your-secret-token-here
```

Every HTTP request must then include the header:

```
Authorization: Bearer your-secret-token-here
```

**mcporter:**
```bash
mcporter config add tradfri --url http://localhost:8765/mcp --header "Authorization: Bearer your-secret-token-here"
```

**MCP Inspector:**
```bash
npx @modelcontextprotocol/inspector http://localhost:8765/mcp --header "Authorization: Bearer your-secret-token-here"
```

Requests without a valid token receive HTTP 401. To run without a token, either bind to loopback (`MCP_HOST=127.0.0.1`) or set `MCP_ALLOW_INSECURE=1` to override the startup check on a trusted LAN.

### Docker Log Rotation (Because Logs Grow Like Weeds)

Container logs auto-rotate (`max-size: 10m`, 3 files, 30MB cap). All MCP tool calls are logged (e.g. `control_by_name(name='Living Room', state=True)`) for debugging without unbounded growth. Your future self will thank you.

---

## Data & Privacy

Short version: **everything stays on your network.** There are no analytics, no tracking pixels, no telemetry, no cloud calls — the only thing this server talks to is your gateway, over encrypted CoAP/DTLS on the LAN.

What it actually stores, and where:

| What | Where | Notes |
|------|-------|-------|
| Device & room names you chose, group/scene topology | `devices.json`, `aliases.json` (local disk, plaintext) | Names like "Kid's Room" plus on/off history can reveal who's home and when — treat as personal data. |
| Tool calls with device names + timestamps | Container/stdout logs | A behavioral trail; auto-rotated (see above). Drop the log level to `WARNING` if you'd rather not keep it. |
| Gateway PSK, IP, optional bearer token | `.tradfri_psk.json`, `.env` | Secrets, not personal data. Keep them git-ignored (they already are). |

**Is this a GDPR thing?** If you're running it for **your own home**, almost certainly not — that's the GDPR "household exemption" ([Art. 2(2)(c)](https://gdpr-info.eu/art-2-gdpr/), Recital 18), and personal/household processing falls outside the regulation. If instead an **organization** deploys it — an office, a landlord, a rental/Airbnb, a care facility — then the names-and-occupancy data relates to identifiable people and GDPR applies. In that case: lock down access with `MCP_AUTH_TOKEN`, consider logging device IDs instead of names, and set a log-retention policy you're comfortable defending.

Nothing here is legal advice — just a map of what the tool touches so you can make the call for your setup.

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
tradfri Living\ Room temp warm
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
tradfri Desk\ Lamp temp warm
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

Ask OpenClaw to "turn on the living room lights" and bask in the glow of success (literally).

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

---

## Disclaimer

This is a personal project I maintain in my free time, provided **as is** without warranty of any kind. Use at your own risk — see [`LICENSE`](LICENSE) (MIT) for the full terms.

- **Not affiliated with IKEA.** "TRADFRI" and "IKEA" are trademarks of Inter IKEA Systems B.V.; this project is independent and not endorsed by, sponsored by, or connected to IKEA. It talks to the gateway over its own CoAP/DTLS interface and may break if IKEA changes that interface.
- **You own your deployment's security.** The server controls real devices in your home and exposes device names over the network. Securing it — setting `MCP_AUTH_TOKEN`, binding appropriately, keeping it off the public internet — is your responsibility. See [Bearer Authentication](#bearer-authentication).
- **Not legal advice.** The [Data & Privacy](#data--privacy) section is general information to help you reason about your setup, not legal advice. If GDPR or another regime applies to your deployment, consult qualified counsel.