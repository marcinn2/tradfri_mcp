# 自製 MCP Server 接進 OpenClaw：以 IKEA TRADFRI 智慧家居為例

> **English summary:** End-to-end tutorial on building a custom MCP Server for IKEA TRADFRI smart home integration with OpenClaw. Covers: architecture design (why FastMCP + Docker + HTTP transport), CoAP device topology management (virtual rooms, alias system), 12 MCP tools (control, color temp, color, scenes, status, OBSERVE push notifications), OpenClaw integration via mcporter skill + wrapper script, and a complete testing strategy. Includes pitfalls specific to macOS Docker networking, 8B LLM tool-calling reliability, and the critical role of AGENTS.md. The document is written in Traditional Chinese.

本文記錄了一個完整的實作歷程：如何在 macOS 上打通 IKEA TRADFRI 智慧家居 gateway 的通訊層，並將控制能力包裝成 MCP Server，讓 OpenClaw AI assistant 能透過自然語言指令操控家中的燈具、插座與場景。

**讀完本文，你能做到：**
- 用自然語言叫 AI「把客廳的燈調暗一點」，燈真的會暗
- 理解為什麼「直接裝 lib 跑起來」在這條路上完全不可行
- 建立一套可複用的 MCP server 開發與整合模式

**本文不是官方文件的翻譯，是踩坑紀錄。**

---

## 環境

| 元件 | 規格 |
|------|------|
| 主機 | Mac Mini（Apple Silicon，macOS 15）|
| AI 平台 | [OpenClaw](https://openclaw.ai) 2026.3.x |
| 智慧家居 | IKEA TRADFRI gateway E1526，韌體 1.21.x |
| 通訊協定 | CoAP over DTLS（CoAPS），port 5684 |
| MCP framework | [FastMCP](https://github.com/jlowin/fastmcp) 3.x |
| 容器 | Docker（Mac Mini 常駐服務）|

---

## 第一章：為什麼這條路這麼難走

### TRADFRI 不是普通的 HTTP API

IKEA TRADFRI gateway 不提供 REST API。它使用的是：

- **CoAP**（Constrained Application Protocol）：IoT 世界的 HTTP，但跑在 UDP 上
- **DTLS 1.2**（Datagram TLS）：CoAP 的加密層，等同於 TLS 但用於 UDP
- **PSK cipher**：`TLS_PSK_WITH_AES_128_CCM_8`，OpenSSL 3.x 不支援

這意味著你不能用 `requests`、`httpx`、甚至 `aiohttp` 直接連它。你需要一個實作了 DTLS + AES-CCM 的 CoAP client。

### 既有函式庫的問題

| 函式庫 | 問題 |
|--------|------|
| `pytradfri`（官方 Python SDK）| 內部用 `aiocoap`，而 aiocoap 的 tinydtls transport 在 macOS 上有 socket 問題 |
| `aiocoap`（預設 libcoap backend）| OpenSSL 3 不支援 AES-CCM，握手直接失敗 |
| `DTLSSocket 0.2.3`（TinyDTLS wrapper）| 有多個 bug 需要 patch TinyDTLS C 原始碼才能在 macOS 上運作 |

完整的 DTLS 踩坑紀錄與修法，請見 [`docs/dtls-tradfri-pitfalls.md`](./dtls-tradfri-pitfalls.md)，本文不重複。

**結論：DTLS 層打通後，捨棄 `pytradfri` 的 model 層（與 gateway 韌體不相容），改用 `aiocoap` 直接發 CoAP 請求，自行解析 JSON。**

---

## 第二章：架構設計

### 整體架構

```
User（Telegram 訊息）
  ↓
OpenClaw（Mac Mini 常駐，AI agent）
  ↓  mcporter skill（OpenClaw 內建）
mcporter CLI（MCP client）
  ↓  HTTP（localhost:8765）
tradfri-mcp（Docker container，FastMCP HTTP server）
  ↓  CoAPS（aiocoap）
TRADFRI gateway（192.168.x.x:5684）
  ↓  Zigbee
燈具、插座、遙控器
```

### 為什麼選這個架構

**為什麼不用 pytradfri？**

`pytradfri` 最新版的 pydantic model 假設 gateway 有回傳 `15025`、`15015` 等欄位，但韌體 1.21.x 不會回傳這些欄位，導致每次呼叫都拋 `ValidationError`。patch 它比自己實作代價更高。

**為什麼用 mcporter 而不是直接改 OpenClaw config？**

OpenClaw 沒有 `mcpServers` config 欄位（與 Claude Desktop 不同）。它的 MCP 整合走 **mcporter skill**：OpenClaw 的 AI agent 透過執行 `mcporter` CLI 來呼叫 MCP tools。這是 OpenClaw 官方推薦的第三方 MCP 整合方式。

**為什麼用 Docker？**

`tradfri-mcp` 需要：
1. 常駐執行（維持 aiocoap event loop）
2. 與 OpenClaw 解耦（獨立升版、重啟）
3. 在 Mac Mini 上以服務形式管理

Docker + `restart: unless-stopped` 是最乾淨的選擇。

**為什麼用 HTTP transport 而不是 stdio？**

stdio transport 每次 tool call 都需要啟動一個新的子 process。常駐的 aiocoap event loop 無法在 stdio 模式下維持。HTTP transport 讓 Docker container 持續跑，mcporter 直接打 HTTP 連進來。

---

## 第三章：MCP Server 設計

### 技術選型：FastMCP 3.x

FastMCP 是目前最主流的 Python MCP server framework：

- FastMCP 1.0 已被併入官方 Python MCP SDK
- FastMCP 3.x 持續獨立維護，每日下載量百萬次
- 用 type hint + docstring 自動生成 MCP tool schema，無需手動定義

```python
from fastmcp import FastMCP

mcp = FastMCP("tradfri")

@mcp.tool()
async def control_group(group_id: int, brightness: int) -> str:
    """控制群組亮度（0–254）。適用於整個房間的燈。"""
    await coap_put(f"/15004/{group_id}", {"5851": brightness})
    return f"群組 {group_id} 亮度設為 {brightness}"
```

### 設備拓撲管理

gateway 上的設備用數字 ID 識別，但 AI 需要知道「客廳 = group_id X」。

**方案：`devices.json` + `aliases.json`**

```jsonc
// devices.json（由 scripts/scan.py 自動產生，不手動維護）
{
  "groups": [
    {"id": 131079, "name": "GU10色溫", "state": true, "brightness": 200}
  ],
  "devices": [...]
}

// aliases.json（由 user 手動維護）
{
  // 虛擬房間（組合多個 IKEA group + 獨立設備）
  "客廳": {
    "type": "virtual",
    "groups": [131079],
    "devices": [65545, 65553, 65554, 65555, 65556, 65572, 65573, 65574]
  },
  // IKEA 原生群組
  "主臥室": {"type": "group", "id": 131089},
  // 設備清單（沒有 IKEA group 時用）
  "餐廳軌道燈": {"type": "device_list", "ids": [65579, 65580, 65581]},
  // 單一設備
  "餐桌燈": {"type": "device", "id": 65551}
}
```

**為什麼需要 `virtual` 類型？**

IKEA TRADFRI 的群組設計是依燈泡型號分類（「GU10色溫」、「GU10彩色」），而不是依房間分類。Apple Home 則按房間管理。`virtual` 類型讓你把跨 IKEA group 的設備組合成邏輯上的「一個房間」，`control_by_name` 工具會自動展開並依序控制所有目標。

### MCP Tools 一覽

| Tool | 說明 |
|------|------|
| `control_group` | 控制整個群組（開關、亮度）|
| `control_device` | 控制單一設備 |
| `control_by_name` | 以 alias 名稱控制（支援 virtual/device_list/group/device）|
| `set_color_temp` | 調整色溫（暖/冷，支援「暖一點」語意）|
| `set_color` | 設定顏色（紅/綠/藍/橙/黃…）|
| `activate_scene` | 觸發場景 |
| `get_status` | 查詢設備或群組當前狀態 |
| `list_devices` | 列出所有設備/群組（含 alias）|
| `list_aliases` | 列出所有 alias 名稱與類型（輕量，LLM 快速確認用）|
| `refresh_devices` | 重新掃描 gateway，更新 devices.json |
| `find_by_name` | 以名稱查找設備/群組 ID |

### 色溫與顏色支援

**色溫（白光燈）**

CoAP key `5711` 單位是 **Mireds**（不是 Kelvin）：

```
Mireds = 1,000,000 / Kelvin
```

| Mireds | Kelvin | 感覺 |
|--------|--------|------|
| 250 | 4000K | 冷白 / 日光 |
| 370 | 2700K | 暖白 / 黃光 |
| 454 | 2200K | 超暖 / 燭光 |

「調暖」= `mireds + 50`，「調冷」= `mireds - 50`，clamp 到 250–454。

**顏色（彩色燈）**

CoAP key `5709`（X）、`5710`（Y），範圍 0–65535：

| 顏色 | X | Y |
|------|---|---|
| 紅 | 45914 | 19661 |
| 綠 | 19661 | 45914 |
| 藍 | 9830 | 3932 |
| 橙 | 42163 | 25887 |
| 黃 | 37449 | 37449 |
| 暖白 | 30140 | 26870 |

---

## 第四章：OpenClaw 整合

### 安裝 mcporter

OpenClaw 已內建 mcporter skill（`/opt/homebrew/lib/node_modules/openclaw/skills/mcporter/`），但需要安裝對應的 binary：

```bash
# 方法一：從 OpenClaw dashboard 的 Skills 頁點 Install
# 方法二：手動
npm install -g mcporter
```

裝好後，`openclaw skills check` 會顯示 `✓ ready   📦 mcporter`。

### 設定 mcporter 指向 tradfri-mcp

```bash
mcporter config add tradfri --url http://localhost:8765/mcp
```

驗證：

```bash
mcporter list tradfri
# → 列出 control_group, control_device, control_by_name, ...

mcporter call tradfri.control_by_name name=客廳 brightness=80
# → 客廳燈暗下來
```

> **注意**：mcporter 的 flag 是 `--url`，不是 `--http-url`。

### 建立 tradfri OpenClaw skill

OpenClaw skill 是一個 SKILL.md 檔，當 user 說出符合 triggers 的話時，OpenClaw 會將 SKILL.md 注入 LLM 的 context，讓 LLM 知道如何呼叫 mcporter。

這比把所有燈具 alias 寫進 system prompt 更乾淨——skill 只在需要時才載入。

建立目錄和檔案：

```bash
mkdir -p ~/.openclaw/workspace/skills/tradfri/.clawhub
```

`~/.openclaw/workspace/skills/tradfri/SKILL.md`：

```markdown
---
name: tradfri
description: IKEA TRADFRI 智慧家居控制——透過 mcporter 控制燈具、插座與場景
author: local
version: 1.0.0
triggers:
  - "開燈"
  - "關燈"
  - "調光"
  - "調亮"
  - "調暗"
  - "色溫"
  - "tradfri"
  - "IKEA"
  - "客廳燈"
  - "臥室燈"
---

# IKEA TRADFRI 智慧家居控制

## How to use

1. 先呼叫 `mcporter call tradfri.list_aliases` 取得可用名稱清單
2. 根據清單選擇正確的名稱，呼叫對應的 tool

## Available tools

### 開關 / 亮度
mcporter call tradfri.control_by_name name=<名稱> state=true/false
mcporter call tradfri.control_by_name name=<名稱> brightness=<0-254>

### 色溫
mcporter call tradfri.set_color_temp name=<名稱> direction=warm/cool

### 顏色（RGB 燈泡專用）
mcporter call tradfri.set_color name=<名稱> color=red/green/blue/orange/yellow

### 查詢
mcporter call tradfri.get_status name=<名稱>
```

`~/.openclaw/workspace/skills/tradfri/_meta.json`：

```json
{
  "slug": "tradfri",
  "version": "1.0.0",
  "description": "IKEA TRADFRI 智慧家居控制"
}
```

`~/.openclaw/workspace/skills/tradfri/.clawhub/origin.json`：

```json
{
  "version": 1,
  "registry": "local",
  "slug": "tradfri",
  "installedVersion": "1.0.0",
  "installedAt": 1773986800000
}
```

重啟 OpenClaw gateway 後，`openclaw skills list` 應顯示 tradfri skill（`✓ ready`，source: `openclaw-workspace`）：

```bash
launchctl unload ~/Library/LaunchAgents/ai.openclaw.gateway.plist
launchctl load  ~/Library/LaunchAgents/ai.openclaw.gateway.plist
openclaw skills list | grep tradfri
# ✓ ready   📦 tradfri   IKEA TRADFRI 智慧家居控制...   openclaw-workspace
```

### OpenClaw Gateway HTTP API（開發用）

OpenClaw gateway 預設監聽 `127.0.0.1:18789`。若要從外部程式（如 Claude Code 的 openclaw-mcp）呼叫，需啟用 HTTP API：

在 `~/.openclaw/openclaw.json` 加入：

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

重啟 gateway 後，`POST http://127.0.0.1:18789/v1/chat/completions` 即可使用。

### 整合測試工具：openclaw-mcp（開發用）

安裝 [freema/openclaw-mcp](https://github.com/freema/openclaw-mcp) 作為 Claude Code 的 MCP server，讓 Claude Code 能直接向 OpenClaw 發訊息，無需透過 Telegram 轉述：

```bash
claude mcp add openclaw npx openclaw-mcp \
  -e OPENCLAW_URL=http://127.0.0.1:18789 \
  -e OPENCLAW_GATEWAY_TOKEN=<your-token> \
  -e OPENCLAW_TIMEOUT_MS=300000
```

Token 在 `~/.openclaw/openclaw.json` 的 `gateway.auth.token` 欄位。

---

## 第五章：測試策略

### 階段一：MCP Server 單獨測試（不需要 PC / Ollama）

**用 mcporter 直打：**

```bash
# 確認 tools 有被正確定義
mcporter list tradfri

# 測試控制
mcporter call tradfri.list_aliases
mcporter call tradfri.control_by_name name=客廳 brightness=50
mcporter call tradfri.set_color_temp name=餐桌燈 direction=warm
mcporter call tradfri.activate_scene group_id=131073 scene_id=196608

# 查詢狀態
mcporter call tradfri.get_status name=客廳
```

**用 MCP Inspector（有 Web UI）：**

```bash
npx @modelcontextprotocol/inspector http://localhost:8765/mcp
```

開啟 `http://localhost:6274` 即可在瀏覽器中列出 tools、發 call、看 request/response。

### 階段二：OpenClaw 整合測試（需要 Ollama 開機）

**透過 Telegram：**

直接用正常 user 流程，觀察 OpenClaw 是否正確呼叫 mcporter。

---

## 第六章：部署

### 目錄結構

```
kc_tradfri_mcp/
├── server.py              # FastMCP server 主程式
├── aliases.json           # user 自訂別名（含 virtual room）
├── devices.json           # 設備清單（scan 產生，.gitignore）
├── .tradfri_psk.json      # PSK 憑證（.gitignore）
├── .env                   # 環境變數（.gitignore）
├── .env.example           # 範本
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── README.md
├── scripts/
│   ├── scan.py            # 掃描 gateway 設備
│   └── gen_psk.py         # 產生 PSK 憑證
└── docs/
    ├── dtls-tradfri-pitfalls.md
    └── openclaw-tradfri-mcp-tutorial.md  ← 本文
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

### 環境變數

```bash
# .env（不進 git）
TRADFRI_GATEWAY_IP=192.168.x.x
```

PSK identity 與 key 存在 `.tradfri_psk.json`（mount 進 container，不進 image）。

---

## 附錄 A：PSK 產生方式

第一次使用前，需要向 gateway 申請一組 PSK（用 security code 換取長期憑證）：

```bash
export TRADFRI_GATEWAY_IP=192.168.x.x
export TRADFRI_SECURITY_CODE=xxxxxxxxxxxxxxxx   # gateway 背面的碼

uv run python scripts/gen_psk.py
# ✓ DTLS 握手完成，gateway 韌體：1.21.xxxx
# ✓ PSK 已存入 .tradfri_psk.json
#   identity: kc-tradfri-xxxxxxxx
#   psk:      xxxx****
```

`gen_psk.py` 的實作細節（DTLS + CoAP POST）請見 [`docs/dtls-tradfri-pitfalls.md`](./dtls-tradfri-pitfalls.md)。

---

## 附錄 B：設備掃描

```bash
export TRADFRI_GATEWAY_IP=192.168.x.x
uv run python scripts/scan.py
# → 輸出所有 devices、groups、scenes 的 JSON
# → 複製到 devices.json
```

建議初次部署時手動執行一次，之後可透過 `refresh_devices` MCP tool 更新。

---

## 附錄 C：TRADFRI CoAP 快速參照

### 資源路徑

| 路徑 | 說明 |
|------|------|
| `GET /15001` | 所有設備 ID 列表 |
| `GET /15001/{id}` | 單一設備詳情 |
| `PUT /15001/{id}` | 控制單一設備 |
| `GET /15004` | 所有群組 ID 列表 |
| `GET /15004/{id}` | 單一群組詳情 |
| `PUT /15004/{id}` | 控制群組 |
| `GET /15005/{gid}` | 群組的場景列表 |
| `GET /15005/{gid}/{sid}` | 場景詳情 |

### 常用 CoAP key

| Key | 含義 | 值域 |
|-----|------|------|
| `9001` | 名稱 | 字串 |
| `9003` | ID | 整數 |
| `5750` | 設備類型 | 0=遙控,2=燈,3=插座 |
| `5850` | 開關狀態 | 0/1 |
| `5851` | 亮度 | 0–254 |
| `5711` | 色溫（Mireds）| 250–454 |
| `5709` | 顏色 X（CIE）| 0–65535 |
| `5710` | 顏色 Y（CIE）| 0–65535 |
| `9039` | 觸發場景 ID | 整數 |

### aiocoap credentials 設定（重要）

URI pattern 不能帶 port 號：

```python
ctx.client_credentials.load_from_dict({
    "coaps://192.168.x.x/*": {      # ← 不要寫 :5684
        "dtls": {
            "psk": psk.encode(),
            "client-identity": identity.encode(),
        }
    }
})
```

---

*本文對應的 MCP server source code：[kc_tradfri_mcp](https://github.com/KerberosClaw/kc_tradfri_mcp)*
*DTLS 踩坑詳細紀錄：[docs/dtls-tradfri-pitfalls.md](./dtls-tradfri-pitfalls.md)*
