# 「把客廳的燈打開」— TRADFRI MCP

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![FastMCP](https://img.shields.io/badge/FastMCP-3.x-orange.svg)](https://github.com/jlowin/fastmcp)
[![MCP](https://img.shields.io/badge/Protocol-MCP-purple.svg)](https://modelcontextprotocol.io)

[English](README.md)

IKEA TRADFRI 智慧家居的 MCP Server。將 CoAP-over-DTLS 通訊封裝成 MCP tools，讓 AI assistant 能用自然語言控制燈具、插座與場景。

> **詳細教程**：[`docs/openclaw-tradfri-mcp-tutorial.md`](docs/openclaw-tradfri-mcp-tutorial.md)
> **DTLS 踩坑紀錄**：[`docs/dtls-tradfri-pitfalls.md`](docs/dtls-tradfri-pitfalls.md)

---

## 架構

```
User（Telegram / Web UI）
  → AI Agent（OpenClaw / Claude Desktop / etc.）
  → mcporter CLI（MCP client）
  → tradfri-mcp（Docker, FastMCP HTTP server, port 8765）
  → aiocoap（CoAP over DTLS）
  → TRADFRI gateway（LAN, UDP 5684）
  → Zigbee → 燈具 / 插座
```

## 功能

- **自然語言控制** — 說「把客廳的燈打開」就能動
- **12 個 MCP tools** — 開關、亮度、色溫、顏色、場景、狀態查詢等
- **別名系統** — 將友善名稱對應到設備、群組或虛擬房間
- **CoAP OBSERVE 推播通知** — 遙控器或 Apple Home 操作燈時，透過 Telegram 通知
- **Docker 部署** — `docker compose up -d`，附 log rotation
- **內建 TinyDTLS** — 已 patch macOS 相容性，不依賴 OpenSSL 3

## 目錄結構

```
kc_tradfri_mcp/
├── server.py              # FastMCP HTTP server（主程式）
├── coap_client.py         # aiocoap 封裝（CoAP GET/PUT，singleton context）
├── config.py              # 環境變數設定
├── devices.py             # 設備拓撲管理（devices.json / aliases.json）
├── aliases.json           # 自訂別名（含 virtual room）
├── .tradfri_psk.json      # PSK 憑證（.gitignore）
├── .env / .env.example    # 環境變數
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml / uv.lock
├── vendor/dtlssocket/     # DTLSSocket 0.2.3（TinyDTLS 已 patch）
├── scripts/
│   ├── gen_psk.py         # 產生 PSK 憑證
│   └── scan.py            # 掃描 gateway 設備
├── openclaw-skill/        # OpenClaw skill（見「OpenClaw 整合」）
│   ├── SKILL.md
│   ├── _meta.json
│   ├── .clawhub/origin.json
│   └── scripts/
│       └── tradfri        # wrapper script（簡化 mcporter 呼叫）
└── docs/
    ├── dtls-tradfri-pitfalls.md
    └── openclaw-tradfri-mcp-tutorial.md
```

---

## 快速開始

### 1. Clone 並安裝依賴

```bash
git clone https://github.com/KerberosClaw/kc_tradfri_mcp.git
cd kc_tradfri_mcp
uv sync
```

### 2. 產生 PSK 憑證

```bash
export TRADFRI_GATEWAY_IP=192.168.x.x
export TRADFRI_SECURITY_CODE=xxxxxxxxxxxxxxxx   # gateway 背面的碼

uv run python scripts/gen_psk.py
# → .tradfri_psk.json 建立完成
```

> 若已有 `.tradfri_psk.json`，跳過此步驟。
> DTLS 相關問題見 [`docs/dtls-tradfri-pitfalls.md`](docs/dtls-tradfri-pitfalls.md)。

### 3. 掃描設備

```bash
uv run python scripts/scan.py
# 輸出存為 devices.json；或啟動後用 mcporter call tradfri.refresh_devices
```

### 4. 設定

```bash
cp .env.example .env
# 編輯 .env，填入 TRADFRI_GATEWAY_IP
```

編輯 `aliases.json`，設定自訂名稱（支援四種類型）：

```json
{
  "客廳": {
    "type": "virtual",
    "groups": [131079],
    "devices": [65545, 65553, 65554, 65555]
  },
  "主臥室": {"type": "group", "id": 131089},
  "餐廳軌道燈": {"type": "device_list", "ids": [65579, 65580, 65581]},
  "餐桌燈": {"type": "device", "id": 65551}
}
```

| 類型 | 說明 |
|------|------|
| `virtual` | 虛擬房間：組合多個 IKEA group + 獨立設備 |
| `group` | IKEA 原生群組 |
| `device_list` | 多個設備的集合（無 IKEA group 時用）|
| `device` | 單一設備 |

### 5. 啟動（Docker）

```bash
docker compose up -d
docker compose logs -f   # 確認 DTLS 握手成功
```

### 6. 連接 mcporter

```bash
npm install -g mcporter
mcporter config add tradfri --url http://localhost:8765/mcp
mcporter list tradfri   # 確認 tools 出現
```

### 7. 測試

```bash
mcporter call tradfri.list_aliases
mcporter call tradfri.control_by_name name=客廳 state=false
mcporter call tradfri.control_by_name name=客廳 state=true
mcporter call tradfri.set_color_temp name=餐桌燈 direction=warm
```

---

## MCP Tools

| Tool | 說明 |
|------|------|
| `control_group` | 控制群組（開關、亮度）|
| `control_device` | 控制單一設備 |
| `control_by_name` | **最常用** — 以 alias 名稱控制（支援所有 alias 類型）|
| `set_color_temp` | 色溫調整（`direction: warm/cool` 或 `mireds: 250-454`）|
| `set_color` | 設定顏色（RGB 燈泡：red/green/blue/orange/yellow/purple/pink）|
| `activate_scene` | 觸發場景 |
| `get_status` | 查詢即時狀態（支援 `name=`）|
| `list_devices` | 列出所有設備、群組、場景、alias |
| `list_aliases` | 列出 alias 清單（輕量，供 LLM 快速確認）|
| `refresh_devices` | 重新掃描 gateway，更新 devices.json |
| `find_by_name` | 名稱 → ID 解析 |
| `send_notification` | Telegram 推播（未設定時靜默略過）|

---

## CoAP OBSERVE（推播通知）

Server 啟動時會對每個 alias 建立 CoAP OBSERVE 訂閱。當燈的狀態改變（例如透過遙控器或 Apple Home），server 偵測到變化後透過 Telegram 發送通知。

**前置需求：** 在 `.env` 設定 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID`。

**行為：**
- 啟動時擷取 baseline 狀態
- 只在**狀態變更**時通知（不通知初始值）
- OBSERVE 訂閱中斷時自動重連（重試間隔：`TRADFRI_POLL_INTERVAL`，預設 30 秒）
- 不干擾控制操作（OBSERVE 擁有 CoAP context 生命週期）

---

## 環境變數

| 變數 | 必填 | 預設 | 說明 |
|------|------|------|------|
| `TRADFRI_GATEWAY_IP` | **是** | — | Gateway LAN IP |
| `MCP_PORT` | | `8765` | HTTP server port |
| `MCP_HOST` | | `0.0.0.0` | Bind address |
| `PSK_FILE` | | `.tradfri_psk.json` | PSK 憑證路徑 |
| `DEVICES_FILE` | | `devices.json` | 設備快取路徑 |
| `ALIASES_FILE` | | `aliases.json` | 別名對應路徑 |
| `TELEGRAM_BOT_TOKEN` | | — | Telegram Bot token（選填，推播通知用）|
| `TELEGRAM_CHAT_ID` | | — | Telegram Chat ID（選填）|
| `TRADFRI_POLL_INTERVAL` | | `30` | OBSERVE 中斷後重試間隔（秒）|

### Docker Log Rotation

Container log 自動 rotate（`max-size: 10m`，保留 3 個檔案，上限 30MB）。所有 MCP tool call 會記錄在 log 中（如 `control_by_name(name='客廳', state=True)`），方便除錯但不會無限成長。

---

## OpenClaw 整合

### 原理

OpenClaw 沒有 `mcpServers` 設定（與 Claude Desktop 不同）。它的 MCP 整合走 **mcporter skill**：AI agent 透過 `exec` 工具執行 `mcporter` CLI 來呼叫 MCP tools。

對較小的 LLM 來說，複雜的 mcporter 語法不夠可靠：

```bash
# 對小型模型太複雜 — 多個 key=value 參數 + 不同 tool 名稱
mcporter call tradfri.control_by_name name=客廳 state=true
mcporter call tradfri.set_color_temp name=客廳 direction=warm
```

解法是 **wrapper script**，把複雜度藏起來，讓 LLM 只需 exec 簡單的中文指令：

```bash
tradfri 客廳 開
tradfri 客廳 關
tradfri 客廳 亮度 80       # 百分比 0-100
tradfri 客廳 色溫 暖
tradfri 餐桌燈 顏色 紅     # RGB 燈泡：紅/綠/藍/橙/黃/紫/粉
tradfri 查詢 客廳
tradfri 列表
```

### 安裝步驟

**前置：** 確認 mcporter 已安裝且已設定（見「快速開始」步驟 6）。

**1. 安裝 OpenClaw skill**

```bash
# 複製到 OpenClaw workspace（不能用 symlink，OpenClaw 會拒絕跨目錄的 realPath）
cp -r openclaw-skill ~/.openclaw/workspace/skills/tradfri
```

**2. 安裝 wrapper script**

```bash
ln -s $(pwd)/openclaw-skill/scripts/tradfri /opt/homebrew/bin/tradfri
# Linux：ln -s $(pwd)/openclaw-skill/scripts/tradfri /usr/local/bin/tradfri
```

**3. 在 AGENTS.md 加入燈控指令**

在 `~/.openclaw/workspace/AGENTS.md` 加入（**不是 systemPrompt，不是 SKILL.md**）：

```markdown
## IKEA TRADFRI 燈控

收到燈控請求 → 立即 exec `tradfri` 指令，不解釋不確認。

tradfri 客廳電視牆 開
tradfri 客廳 關
tradfri 客廳 亮度 80
tradfri 餐桌燈 色溫 暖
tradfri 餐桌燈 顏色 紅
tradfri 查詢 沙發燈
tradfri 列表
```

> **重要：** 只有 AGENTS.md 的內容會被完整注入到 LLM context。systemPrompt 和 SKILL.md 不可靠。

**4. 重啟 OpenClaw gateway**

```bash
launchctl kickstart -k gui/$(id -u)/ai.openclaw.gateway
```

**5. 測試**

在 Telegram 對 OpenClaw 說「開客廳燈」，確認燈亮起來。

---

## 踩坑紀錄

### Docker `network_mode: host` 在 macOS 不能用

macOS Docker Desktop 跑在 LinuxKit VM 裡，`network_mode: host` 只暴露 VM 的網路，不是 Mac 的 LAN。

**解法：** 使用預設 bridge 網路 + `ports` 映射。bridge 網路可以透過 VM NAT 存取 LAN IP（包括 gateway 的 UDP 5684）。此方案在 macOS 和 Linux 都能用。

```yaml
# docker-compose.yml
services:
  tradfri-mcp:
    ports:
      - "8765:8765"     # 不要用 network_mode: host
```

### CoAP context 的所有權：OBSERVE 負責 reset

原始設計中 `coap_put` / `coap_get` 失敗時會 `_ctx = None` 重置 context。但這會破壞正在運作的 OBSERVE session（因為 TRADFRI gateway 每個 PSK identity 只允許一個 DTLS session）。

**正確做法：**
- `coap_put` / `coap_get` 失敗時 **不 reset context**，直接 raise
- OBSERVE task 偵測到連線中斷後，才呼叫 `reset_ctx()` 清除舊 context
- 下次 `get_ctx()` 時自動建立新的 DTLS session

### OBSERVE 不需要 semaphore 序列化

曾經嘗試用 `asyncio.Semaphore(1)` + 2 秒延遲來序列化 OBSERVE 初始化，認為 20 個並發 GET 會壓垮 gateway。實測證明不需要：gateway 可以處理並發 OBSERVE GET，問題根源是上面的 context reset bug，不是並發量。

移除 semaphore 後 OBSERVE 初始化時間從 ~40 秒降到幾秒。

### OpenClaw skill 不能用 symlink

`~/.openclaw/workspace/skills/tradfri` 如果是 symlink 指向 repo 目錄，OpenClaw 會拒絕載入：`Skipping skill path that resolves outside its configured root.`。必須用 `cp -r` 複製實際檔案。

### OpenClaw 只有 AGENTS.md 會被完整注入 LLM context

`openclaw.json` 的 `systemPrompt` 被放在 system prompt 末尾，容易被截斷或被模型忽略。`SKILL.md` 只有 name/description 被引用，內容不注入。只有 `AGENTS.md` 的內容完整出現在 LLM 看到的 system prompt 中。所有關鍵指令（燈控、搜尋）都要寫在 AGENTS.md。

### aliases.json 的 `_comment` 會導致 list_devices crash

`aliases.json` 裡的 `"_comment": "..."` 是 string，`list_devices` 裡 `target.get("type")` 會 crash。修法：跳過非 dict 的 entries。

---

## 常見問題

| 錯誤 | 解法 |
|------|------|
| `CredentialsMissingError` | credentials URI 去掉 `:5684` port — 見 [`dtls-tradfri-pitfalls.md` #9](docs/dtls-tradfri-pitfalls.md) |
| DTLS 握手失敗 | 需 patch TinyDTLS C 原始碼 — 見 [`dtls-tradfri-pitfalls.md` #6 #7](docs/dtls-tradfri-pitfalls.md) |
| `NetworkError` 循環失敗 | 確認 `coap_client.py` 的 `coap_put`/`coap_get` 沒有 `_ctx = None`（見上方踩坑紀錄）|
| 設備找不到 | `mcporter call tradfri.refresh_devices` 或 `uv run python scripts/scan.py` |
| mcporter 連不上 | `docker compose ps` 確認容器運作，`curl http://localhost:8765/mcp` 確認 HTTP |
| Docker 容器無法連 gateway | macOS 不支援 `network_mode: host`，改用 bridge + `ports`（見上方踩坑紀錄）|

---

## 本機開發（不使用 Docker）

```bash
TRADFRI_GATEWAY_IP=192.168.x.x uv run python server.py

# MCP Inspector（Web UI）
npx @modelcontextprotocol/inspector http://localhost:8765/mcp
# → http://localhost:6274
```


