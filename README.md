# kc_tradfri_mcp

> [English](#english) | [繁體中文](#繁體中文)

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![FastMCP](https://img.shields.io/badge/FastMCP-3.x-orange.svg)](https://github.com/jlowin/fastmcp)
[![MCP](https://img.shields.io/badge/Protocol-MCP-purple.svg)](https://modelcontextprotocol.io)

---

## English

MCP Server for IKEA TRADFRI smart home gateway. Wraps CoAP-over-DTLS communication into clean MCP tools, letting AI assistants control lights, plugs, and scenes with natural language.

> **Full tutorial** (architecture decisions, DTLS pitfalls, OpenClaw integration):
> [`docs/openclaw-tradfri-mcp-tutorial.md`](docs/openclaw-tradfri-mcp-tutorial.md)

### Features

| Feature | Detail |
|---------|--------|
| 🔦 Light control | On/off + brightness (0–254) per device or group |
| 🌡️ Color temperature | Warm/cool adjustment in Mireds (2200K–4000K) |
| 🎨 Color | CIE XY color space — red, green, blue, orange, yellow, purple, pink… |
| 🎬 Scenes | Trigger any gateway scene with one tool call |
| 🗺️ Alias mapping | Map natural names ("客廳") to device/group IDs, including virtual rooms |
| 🔄 Device refresh | Rescan gateway and diff topology changes |
| 🐳 Docker-ready | Single `docker compose up -d` to run as a persistent service |
| 🤖 OpenClaw-ready | Works with OpenClaw via mcporter skill (no config edits needed) |

### Requirements

- macOS or Linux (Windows untested)
- Python 3.12+ via [uv](https://docs.astral.sh/uv/)
- Docker (recommended for persistent deployment)
- Node.js 20+ (for mcporter)
- IKEA TRADFRI gateway E1526 (firmware 1.21.x+)
- TRADFRI Security Code (printed on the gateway label)

### Quick Start

**1. Clone & install dependencies**

```bash
git clone https://github.com/YOUR_USERNAME/kc_tradfri_mcp.git
cd kc_tradfri_mcp
uv sync
```

**2. Generate PSK credentials**

```bash
export TRADFRI_GATEWAY_IP=192.168.x.x
export TRADFRI_SECURITY_CODE=xxxxxxxxxxxxxxxx   # from gateway label

uv run python scripts/gen_psk.py
# → .tradfri_psk.json created
```

> **DTLS Note**: PSK generation uses a patched TinyDTLS stack required on macOS.
> See [`docs/dtls-tradfri-pitfalls.md`](docs/dtls-tradfri-pitfalls.md) for details.
> If you already have `.tradfri_psk.json`, skip this step.

**3. Scan devices**

```bash
export TRADFRI_GATEWAY_IP=192.168.x.x
uv run python scripts/scan.py
# Copy the output into devices.json
```

Or use the MCP tool after starting the server:
```bash
mcporter call tradfri.refresh_devices
```

**4. Configure**

```bash
cp .env.example .env
# Edit .env — set TRADFRI_GATEWAY_IP
```

Edit `aliases.json` to map friendly names to device/group IDs:

```json
{
  "Living Room": {
    "type": "virtual",
    "groups": [131079],
    "devices": [65545, 65553, 65554, 65555]
  },
  "Bedroom": {"type": "group", "id": 131089},
  "Desk Lamp": {"type": "device", "id": 65537}
}
```

**5. Start (Docker)**

```bash
docker compose up -d
docker compose logs -f   # verify startup
```

**6. Connect mcporter**

```bash
npm install -g mcporter
mcporter config add tradfri --url http://localhost:8765/mcp
mcporter list tradfri          # verify tools appear
```

**7. Test**

```bash
mcporter call tradfri.list_aliases
mcporter call tradfri.control_by_name name="Living Room" brightness=80
mcporter call tradfri.set_color_temp name="Desk Lamp" direction=warm
```

### MCP Tools

| Tool | Description |
|------|-------------|
| `control_group` | Control an entire group (state, brightness) |
| `control_device` | Control a single device |
| `control_by_name` | Control by alias name (supports virtual/group/device_list/device) |
| `set_color_temp` | Set color temperature (`mireds` or `direction: warm/cool`) |
| `set_color` | Set color by name (RGB bulbs only) |
| `activate_scene` | Trigger a scene |
| `get_status` | Query live device/group state |
| `list_devices` | List all devices, groups, scenes + aliases |
| `list_aliases` | List all alias names and types (lightweight, for LLM) |
| `refresh_devices` | Rescan gateway and update `devices.json` |
| `find_by_name` | Resolve alias or name to device/group ID |
| `send_notification` | Push a message to Telegram (no-op if not configured) |

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TRADFRI_GATEWAY_IP` | ✅ | — | Gateway LAN IP |
| `MCP_PORT` | | `8765` | HTTP server port |
| `MCP_HOST` | | `0.0.0.0` | Bind address |
| `PSK_FILE` | | `.tradfri_psk.json` | PSK credentials path |
| `DEVICES_FILE` | | `devices.json` | Device topology cache |
| `ALIASES_FILE` | | `aliases.json` | Name → ID mapping |
| `TELEGRAM_BOT_TOKEN` | | — | Telegram Bot token (optional, for push notifications) |
| `TELEGRAM_CHAT_ID` | | — | Telegram Chat ID to send notifications to (optional) |

### OpenClaw Integration

1. Install mcporter binary from OpenClaw dashboard (Skills page) or `npm install -g mcporter`
2. `mcporter config add tradfri --url http://localhost:8765/mcp`
3. Copy `docs/openclaw-tradfri-mcp-tutorial.md` section "建立 tradfri OpenClaw skill" to create the skill
4. Tell OpenClaw: *"Turn off the living room lights"* — it calls mcporter automatically

### Troubleshooting

| Error | Fix |
|-------|-----|
| `CredentialsMissingError` | Remove `:5684` port from credential URI — see pitfalls doc #9 |
| DTLS handshake fails | Patch TinyDTLS C source — see `docs/dtls-tradfri-pitfalls.md` #6 #7 |
| Device not found | Run `refresh_devices` tool or `scripts/scan.py` |
| mcporter can't connect | Check `docker compose ps`, verify port 8765 is free |

### Development (without Docker)

```bash
TRADFRI_GATEWAY_IP=192.168.x.x uv run python server.py

# Debug with MCP Inspector (Web UI)
npx @modelcontextprotocol/inspector http://localhost:8765/mcp
# → open http://localhost:6274
```

---

### 🤖 Claude Code — Unattended Installation Prompt

Copy the block below and paste it into a Claude Code session. Claude will handle the full installation interactively, asking only for information it cannot find itself.

```
You are installing kc_tradfri_mcp, an MCP server for IKEA TRADFRI smart home control.
The repository is already cloned at the current working directory.

Follow these steps in order. Use your tools to execute commands and read files.
Ask the user only when you need information you cannot find (gateway IP, security code).
Do not skip steps or ask for confirmation before each step — just proceed.

STEP 1 — Check prerequisites
  - Verify uv is installed (`uv --version`). If not, install via `curl -LsSf https://astral.sh/uv/install.sh | sh`.
  - Verify Docker is running (`docker info`). If not, tell the user to start Docker and wait.
  - Verify Node.js ≥ 20 (`node --version`). If not, tell the user to install Node.js.

STEP 2 — Install Python dependencies
  Run `uv sync` in the kc_tradfri_mcp directory.

STEP 3 — Check for existing PSK
  - Look for `.tradfri_psk.json` in the repo root.
  - If found and valid JSON with "identity" and "psk" keys, skip to STEP 5.
  - If not found, proceed to STEP 4.

STEP 4 — Generate PSK
  - Ask the user: "What is your TRADFRI gateway IP address?" and "What is the Security Code on the gateway label?"
  - Set environment variables and run `uv run python scripts/gen_psk.py`.
  - Verify `.tradfri_psk.json` was created successfully.

STEP 5 — Scan devices
  - Run `TRADFRI_GATEWAY_IP=<ip> uv run python scripts/scan.py`.
  - Save the output as `devices.json`.

STEP 6 — Configure environment
  - Copy `.env.example` to `.env`.
  - Set `TRADFRI_GATEWAY_IP` in `.env` to the value from STEP 4 (or ask if not known).

STEP 7 — Configure aliases
  - Read `devices.json` to find the group names and IDs.
  - Ask the user: "What names do you want to use for each room?"
  - Write the responses into `aliases.json`.

STEP 8 — Start Docker container
  - Run `docker compose up -d --build` in the kc_tradfri_mcp directory.
  - Run `docker compose logs kc_tradfri_mcp` and verify the server started on port 8765.

STEP 9 — Install and configure mcporter
  - Run `npm install -g mcporter`.
  - Run `mcporter config add tradfri --url http://localhost:8765/mcp`.
  - Run `mcporter list tradfri` and confirm tools appear.

STEP 10 — Smoke test
  - Run `mcporter call tradfri.list_aliases` and show the user the result.
  - Run `mcporter call tradfri.control_by_name name=<first_alias> state=true`.
  - Report success or any errors found.

If any step fails, read the error carefully, check the Troubleshooting section in README.md,
and attempt to fix before asking the user.
```

---

## 繁體中文

IKEA TRADFRI 智慧家居的 MCP Server。將 CoAP-over-DTLS 通訊封裝成 MCP tools，讓 AI assistant 能用自然語言控制燈具、插座與場景。

> **完整教程**（架構決策、DTLS 踩坑、OpenClaw 整合）：
> [`docs/openclaw-tradfri-mcp-tutorial.md`](docs/openclaw-tradfri-mcp-tutorial.md)

### 功能特色

| 功能 | 說明 |
|------|------|
| 🔦 燈光控制 | 單一設備或群組的開關與亮度（0–254）|
| 🌡️ 色溫調整 | 暖白 / 冷白相對調整，單位 Mireds（2200K–4000K）|
| 🎨 顏色控制 | CIE XY 色彩空間——紅、綠、藍、橙、黃、紫、粉… |
| 🎬 場景觸發 | 一個 tool call 觸發任意 gateway 場景 |
| 🗺️ 別名映射 | 將「客廳」等自然名稱對應到設備/群組 ID，支援虛擬房間 |
| 🔄 設備重新掃描 | 重新掃描並 diff 拓撲變動 |
| 🐳 Docker 部署 | `docker compose up -d` 啟動常駐服務 |
| 🤖 OpenClaw 整合 | 透過 mcporter skill 接入，無需修改 OpenClaw 設定 |

### 環境需求

- macOS 或 Linux（Windows 未測試）
- Python 3.12+，透過 [uv](https://docs.astral.sh/uv/) 管理
- Docker（建議，常駐服務）
- Node.js 20+（mcporter 所需）
- IKEA TRADFRI gateway E1526（韌體 1.21.x+）
- gateway 背面標籤的 Security Code

### 快速開始

**1. Clone 並安裝依賴**

```bash
git clone https://github.com/YOUR_USERNAME/kc_tradfri_mcp.git
cd kc_tradfri_mcp
uv sync
```

**2. 產生 PSK 憑證**

```bash
export TRADFRI_GATEWAY_IP=192.168.x.x
export TRADFRI_SECURITY_CODE=xxxxxxxxxxxxxxxx   # gateway 背面的碼

uv run python scripts/gen_psk.py
# → .tradfri_psk.json 建立完成
```

> **DTLS 說明**：PSK 產生需要 patch 過的 TinyDTLS 函式庫（macOS 限定問題）。
> 詳見 [`docs/dtls-tradfri-pitfalls.md`](docs/dtls-tradfri-pitfalls.md)。
> 若已有 `.tradfri_psk.json`，跳過此步驟。

**3. 掃描設備**

```bash
export TRADFRI_GATEWAY_IP=192.168.x.x
uv run python scripts/scan.py
# 將輸出存為 devices.json，或啟動後呼叫 refresh_devices tool
```

**4. 設定環境**

```bash
cp .env.example .env
# 編輯 .env，填入 TRADFRI_GATEWAY_IP
```

編輯 `aliases.json`，設定自訂名稱與 ID 的對應：

```json
{
  "客廳": {
    "type": "virtual",
    "groups": [131079],
    "devices": [65545, 65553, 65554, 65555]
  },
  "主臥室": {"type": "group", "id": 131089},
  "餐桌燈": {"type": "device", "id": 65551}
}
```

**5. 啟動（Docker）**

```bash
docker compose up -d
docker compose logs -f   # 確認啟動正常
```

**6. 連接 mcporter**

```bash
npm install -g mcporter
mcporter config add tradfri --url http://localhost:8765/mcp
mcporter list tradfri   # 確認 tools 出現
```

**7. 測試**

```bash
mcporter call tradfri.list_aliases
mcporter call tradfri.control_by_name name=客廳 brightness=80
mcporter call tradfri.set_color_temp name=餐桌燈 direction=warm
```

### MCP Tools 一覽

| Tool | 說明 |
|------|------|
| `control_group` | 控制群組（開關、亮度）|
| `control_device` | 控制單一設備 |
| `control_by_name` | 以 alias 名稱控制（支援 virtual/group/device_list/device）|
| `set_color_temp` | 設定色溫（Mireds 或 warm/cool 方向）|
| `set_color` | 設定顏色（RGB 燈泡專用）|
| `activate_scene` | 觸發場景 |
| `get_status` | 查詢設備/群組即時狀態 |
| `list_devices` | 列出所有設備、群組、場景與 alias |
| `list_aliases` | 列出所有 alias 名稱與類型（輕量版，供 LLM 快速確認）|
| `refresh_devices` | 重新掃描 gateway，更新 devices.json |
| `find_by_name` | 以名稱或 alias 查找 ID |
| `send_notification` | 推播訊息到 Telegram（未設定時靜默略過）|

### OpenClaw 整合

1. 在 OpenClaw dashboard 的 Skills 頁安裝 mcporter，或執行 `npm install -g mcporter`
2. `mcporter config add tradfri --url http://localhost:8765/mcp`
3. 依 `docs/openclaw-tradfri-mcp-tutorial.md` 建立 tradfri OpenClaw skill
4. 在 Telegram 對 OpenClaw 說「把客廳的燈關掉」——它會自動呼叫 mcporter

### 常見問題

| 錯誤 | 解法 |
|------|------|
| `CredentialsMissingError` | credentials URI 去掉 `:5684` port，見踩坑文件 #9 |
| DTLS 握手失敗 | 需 patch TinyDTLS C 原始碼，見 `docs/dtls-tradfri-pitfalls.md` #6 #7 |
| 設備找不到 | 執行 `refresh_devices` tool 或重新跑 `scripts/scan.py` |
| mcporter 連不上 | 確認 `docker compose ps`，確認 port 8765 未被佔用 |

---

## License

MIT © 2026 Kerberos Claw
