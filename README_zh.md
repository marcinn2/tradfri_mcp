# 「把客廳的燈打開」-- 一個真的聽得懂人話的 TRADFRI MCP

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://python.org)
[![FastMCP](https://img.shields.io/badge/FastMCP-3.x-orange.svg)](https://github.com/jlowin/fastmcp)
[![MCP](https://img.shields.io/badge/Protocol-MCP-purple.svg)](https://modelcontextprotocol.io)

[English](README.md)

IKEA TRADFRI 智慧家居的 MCP Server。因為跟瑞典燈泡溝通的唯一方式居然是 CoAP-over-DTLS，所以這個專案把那一大堆協定儀式包裝成 MCP tools，讓 AI assistant 能用自然語言控制燈具、插座與場景。不需要 IoT 協定博士學位（雖然寫這個的時候差點念了一個）。

> **詳細教程（又名戰地日記）**：[`docs/openclaw-tradfri-mcp-tutorial.md`](docs/openclaw-tradfri-mcp-tutorial.md)
> **DTLS 踩坑紀錄（又名「為什麼什麼都不會動」）**：[`docs/dtls-tradfri-pitfalls.md`](docs/dtls-tradfri-pitfalls.md)

---

## 這一整套是怎麼串起來的

```
User（Telegram / Web UI）
  → AI Agent（OpenClaw / Claude Desktop / etc.）
  → mcporter CLI（MCP client）
  → tradfri-mcp（Docker, FastMCP HTTP server, port 8765）
  → aiocoap（CoAP over DTLS）
  → TRADFRI gateway（LAN, UDP 5684）
  → Zigbee → 燈具 / 插座
```

## 它到底能幹嘛

- **自然語言控制** -- 說「把客廳的燈打開」就能動，每次成功的時候都還是覺得很神奇
- **12 個 MCP tools** -- 開關、亮度、色溫、顏色、場景、狀態查詢，可能比你需要的還多
- **別名系統** -- 將友善名稱對應到設備、群組或虛擬房間，因為沒人想記住設備 ID 65553
- **Docker 部署** -- `docker compose up -d`，附 log rotation，像個負責任的工程師
- **內建 TinyDTLS** -- 已 patch macOS 相容性，不依賴 OpenSSL 3，因為那條路只通往淚水

## 什麼東西放在哪裡

```
tradfri_mcp/
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

> **安全聲明：** 本專案設計用於受信任的家庭內網環境。MCP Server 不含 TLS 加密。在預設的 `0.0.0.0` bind 下，它**要求**透過 `MCP_AUTH_TOKEN` 設定 Bearer token，未設定則拒絕啟動（見 [Bearer 認證](#bearer-認證)）——但沒有 TLS 時該 token 會以明文傳輸。請勿在未加裝 TLS-terminating 反向代理的情況下將服務埠暴露到公網。

## 快速開始（樂觀版）

### 1. Clone 並安裝依賴

```bash
git clone https://github.com/marcinn2/tradfri_mcp.git
cd tradfri_mcp
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
> DTLS 相關問題見 [`docs/dtls-tradfri-pitfalls.md`](docs/dtls-tradfri-pitfalls.md)。你大概會用到。

### 3. 掃描設備

```bash
uv run python scripts/scan.py
# 輸出存為 devices.json；或啟動後用 mcporter call tradfri.refresh_devices
```

### 4. 設定（難得簡單的一步）

```bash
cp .env.example .env
# 編輯 .env，填入 TRADFRI_GATEWAY_IP
# 並設定 MCP_AUTH_TOKEN 為任意秘密字串
```

Server 綁定在 `0.0.0.0`（LAN 可連），因此**必須設定 `MCP_AUTH_TOKEN`**，否則拒絕啟動。挑一個不易猜的字串即可——第 6 步要把同樣的值傳給 MCP client。（只在本機跑？改設 `MCP_HOST=127.0.0.1`，就可以略過 token。）

編輯 `aliases.json`，設定自訂名稱。支援四種類型，因為一種太簡單了嘛：

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
mcporter config add tradfri --url http://localhost:8765/mcp --header "Authorization: Bearer your-secret-token-here"
mcporter list tradfri   # 確認 tools 出現
```

請使用與 `MCP_AUTH_TOKEN` 相同的值。（若你綁定 `127.0.0.1` 且未設 token，去掉 `--header` 即可。）

### 7. 見證奇蹟的時刻

```bash
mcporter call tradfri.list_aliases
mcporter call tradfri.control_by_name name=客廳 state=false
mcporter call tradfri.control_by_name name=客廳 state=true
mcporter call tradfri.set_color_temp name=餐桌燈 direction=warm
```

---

## MCP Tools（你的新遙控器）

| Tool | 說明 |
|------|------|
| `control_group` | 控制群組（開關、亮度）|
| `control_device` | 控制單一設備 |
| `control_by_name` | **最常用** -- 以 alias 名稱控制（支援所有 alias 類型）|
| `set_color_temp` | 色溫調整（`direction: warm/cool` 或 `mireds: 250-454`）|
| `set_color` | 設定顏色（RGB 燈泡：red/green/blue/orange/yellow/purple/pink）|
| `activate_scene` | 觸發場景 |
| `get_status` | 查詢即時狀態（支援 `name=`）|
| `battery_report` | 列出遙控器／感測器／窗簾的電量，由低到高排序（`threshold=` 篩選、`live=true` 重新查詢）|
| `list_devices` | 列出所有設備、群組、場景、alias |
| `list_aliases` | 列出 alias 清單（輕量，供 LLM 快速確認）|
| `refresh_devices` | 重新掃描 gateway，更新 devices.json |
| `find_by_name` | 名稱 → ID 解析 |

---

## Prompts（一鍵情境）

Server 也內建可重用的 **MCP prompts**——模板化的情境，client 可以當成 slash command 或快捷動作呈現。它們不會直接操作 gateway；每個 prompt 只是把一份計畫交給 assistant，由它去呼叫上面的 tools，所以你仍能看到即將變更的內容。

| Prompt | 參數 | 作用 |
|--------|------|------|
| `movie_night` | `room`（預設 `Living Room`）| 調暗 + 暖光，適合看電影 |
| `good_morning` | `room`（預設 `Bedroom`）| 全亮、冷白光叫你起床 |
| `good_night` | `keep_on`（選填）| 全部關燈；可選擇留一間房調暗 |
| `set_mood` | `room`、`mood` | 把心情（cozy/focus/party/relax…）轉成亮度／色溫／顏色 |
| `battery_check` | -- | 回報電池設備，標出電量偏低者 |

---

## 環境變數

| 變數 | 必填 | 預設 | 說明 |
|------|------|------|------|
| `TRADFRI_GATEWAY_IP` | **是** | -- | Gateway LAN IP |
| `MCP_PORT` | | `8765` | HTTP server port |
| `MCP_HOST` | | `0.0.0.0` | Bind address |
| `PSK_FILE` | | `.tradfri_psk.json` | PSK 憑證路徑 |
| `DEVICES_FILE` | | `devices.json` | 設備快取路徑 |
| `ALIASES_FILE` | | `aliases.json` | 別名對應路徑 |
| `MCP_AUTH_TOKEN` | | -- | HTTP 認證的 Bearer token（未設定則停用）|
| `MCP_ALLOW_INSECURE` | | `false` | 允許非 loopback bind 且無 token（信任的 LAN 才用）|

### Docker Log Rotation（因為 Log 長得跟雜草一樣快）

Container log 自動 rotate（`max-size: 10m`，保留 3 個檔案，上限 30MB）。所有 MCP tool call 會記錄在 log 中（如 `control_by_name(name='客廳', state=True)`），方便除錯但不會無限成長。未來的你會感謝現在的你。

### Bearer 認證

Server 預設綁定 `0.0.0.0`（讓其他主機／Docker 連得到）。由於這會把家庭控制權與設備名稱暴露給網路上任何人，**在非 loopback bind 下，未設 token 時 server 會拒絕啟動**。啟動時的判斷如下：

- 有設 `MCP_AUTH_TOKEN` → 啟動並要求認證 ✅（建議）
- `MCP_HOST=127.0.0.1` → 啟動（僅本機可連）✅
- 兩者皆無，但 `MCP_ALLOW_INSECURE=1` → 啟動並印出明顯警告 ⚠️（僅信任的 LAN）
- 兩者皆無，也未覆寫 → **拒絕啟動**並附上修正說明 ❌

要求 Bearer token，在 `.env` 設定 `MCP_AUTH_TOKEN`：

```bash
MCP_AUTH_TOKEN=your-secret-token-here
```

之後每個 HTTP 請求都必須帶上 header：

```
Authorization: Bearer your-secret-token-here
```

沒有有效 token 的請求會收到 HTTP 401。若想不帶 token 執行，請改綁 loopback（`MCP_HOST=127.0.0.1`），或在信任的 LAN 上設 `MCP_ALLOW_INSECURE=1` 來覆寫啟動檢查。

---

## 資料與隱私

簡單說：**一切都留在你的網路內。** 沒有任何分析、追蹤像素、遙測或雲端呼叫——這個 server 只會透過 LAN 上加密的 CoAP/DTLS 跟你的 gateway 溝通。

它實際儲存什麼、存在哪：

| 內容 | 位置 | 備註 |
|------|------|------|
| 你取的設備／房間名稱、群組／場景拓樸 | `devices.json`、`aliases.json`（本機磁碟，明文）| 「小孩房」這類名稱加上開關紀錄，可推斷誰在家、何時在家——請當作個人資料看待。|
| 含設備名稱與時間戳的 tool call | Container／stdout log | 一條行為軌跡；會自動 rotate（見上）。不想留的話可把 log level 調到 `WARNING`。|
| Gateway PSK、IP、選填 bearer token | `.tradfri_psk.json`、`.env` | 機密，非個人資料。請保持 git-ignore（預設已是）。|

**這算 GDPR 的事嗎？** 如果你是為**自己家**而跑，幾乎可以肯定不算——這屬於 GDPR 的「家庭豁免」（[Art. 2(2)(c)](https://gdpr-info.eu/art-2-gdpr/)、Recital 18），純個人／家庭處理落在規範之外。但若是**組織**部署——辦公室、房東、出租／Airbnb、照護機構——那麼名稱與在家與否的資料就關聯到可識別的人，GDPR 即適用。此時：用 `MCP_AUTH_TOKEN` 鎖住存取、考慮記錄設備 ID 而非名稱，並訂定一套你能自圓其說的 log 保留政策。

以上不構成法律意見——只是把這個工具碰到的東西攤開來，讓你能為自己的情境做判斷。

---

## OpenClaw 整合（好戲上場了）

### 原理

OpenClaw 沒有 `mcpServers` 設定（跟 Claude Desktop 不同——要是有的話該多好）。它的 MCP 整合走 **mcporter skill**：AI agent 透過 `exec` 工具執行 `mcporter` CLI 來呼叫 MCP tools。

問題來了：對較小的 LLM 來說，複雜的 mcporter 語法大約跟巧克力茶壺一樣可靠：

```bash
# 對小型模型太複雜 — 多個 key=value 參數 + 不同 tool 名稱
mcporter call tradfri.control_by_name name=客廳 state=true
mcporter call tradfri.set_color_temp name=客廳 direction=warm
```

解法是 **wrapper script**，把那些囉嗦的細節全部藏起來：

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

在 `~/.openclaw/workspace/AGENTS.md` 加入（**不是 systemPrompt，不是 SKILL.md** -- 這點相信我就對了）：

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

> **重要：** 只有 AGENTS.md 的內容會被完整注入到 LLM context。systemPrompt 和 SKILL.md 不可靠。這個我 debug 了很久才搞懂。

**4. 重啟 OpenClaw gateway**

```bash
launchctl kickstart -k gui/$(id -u)/ai.openclaw.gateway
```

**5. 測試**

對 OpenClaw 說「開客廳燈」，然後沐浴在成功的光芒中（字面意義上的）。

---

## 踩坑紀錄（幫你先踩過了）

### Docker `network_mode: host` 在 macOS 不能用

macOS Docker Desktop 跑在 LinuxKit VM 裡，`network_mode: host` 只暴露 VM 的網路，不是 Mac 的 LAN。這就是那種在 Linux 上完美運作、到 macOS 上就嘲笑你的東西。

**解法：** 使用預設 bridge 網路 + `ports` 映射。bridge 網路可以透過 VM NAT 存取 LAN IP（包括 gateway 的 UDP 5684）。此方案在 macOS 和 Linux 都能用。無聊，但正確。

```yaml
# docker-compose.yml
services:
  tradfri-mcp:
    ports:
      - "8765:8765"     # 不要用 network_mode: host
```

### OpenClaw skill 不能用 symlink

`~/.openclaw/workspace/skills/tradfri` 如果是 symlink 指向 repo 目錄，OpenClaw 會拒絕載入：`Skipping skill path that resolves outside its configured root.`。必須用 `cp -r` 複製實際檔案。不是我選擇要死在這個山頭上的。

### OpenClaw 只有 AGENTS.md 會被完整注入 LLM context

`openclaw.json` 的 `systemPrompt` 被放在 system prompt 末尾，容易被截斷或被模型忽略。`SKILL.md` 只有 name/description 被引用，內容不注入。只有 `AGENTS.md` 的內容完整出現在 LLM 看到的 system prompt 中。所有關鍵指令（燈控、搜尋）都要寫在 AGENTS.md。我花了令人尷尬的時間才搞清楚這件事。

### aliases.json 的 `_comment` 會導致 list_devices crash

`aliases.json` 裡的 `"_comment": "..."` 是 string，`list_devices` 裡 `target.get("type")` 會 crash。修法：跳過非 dict 的 entries。那種修 2 秒鐘但找 2 小時的 bug。

---

## 常見問題（「為什麼不會動」專區）

| 錯誤 | 解法 |
|------|------|
| `CredentialsMissingError` | credentials URI 去掉 `:5684` port -- 見 [`dtls-tradfri-pitfalls.md` #9](docs/dtls-tradfri-pitfalls.md) |
| DTLS 握手失敗 | 需 patch TinyDTLS C 原始碼 -- 見 [`dtls-tradfri-pitfalls.md` #6 #7](docs/dtls-tradfri-pitfalls.md) |
| `NetworkError` 循環失敗 | 確認 `coap_client.py` 的 `coap_put`/`coap_get` 沒有 `_ctx = None`（見上方踩坑紀錄）|
| 設備找不到 | `mcporter call tradfri.refresh_devices` 或 `uv run python scripts/scan.py` |
| mcporter 連不上 | `docker compose ps` 確認容器運作，`curl http://localhost:8765/mcp` 確認 HTTP |
| Docker 容器無法連 gateway | macOS 不支援 `network_mode: host`，改用 bridge + `ports`（見上方踩坑紀錄）|

---

## 本機開發（不用 Docker 的冒險之旅）

```bash
TRADFRI_GATEWAY_IP=192.168.x.x uv run python server.py

# MCP Inspector（Web UI）
npx @modelcontextprotocol/inspector http://localhost:8765/mcp
# → http://localhost:6274
```

---

## 相關專案（我做的其他東西）

- [kc_openclaw_local_llm](https://github.com/KerberosClaw/kc_openclaw_local_llm) -- OpenClaw + 本地 LLM：哪些真的能用
- [kc_ai_skills](https://github.com/KerberosClaw/kc_ai_skills) -- AI Skills：真的會做事的那種

---

## 免責聲明

這是我利用空閒時間維護的個人專案，**按現狀（as is）** 提供，不附帶任何形式的保證。使用風險自負——完整條款見 [`LICENSE`](LICENSE)（MIT）。

- **與 IKEA 無關。**「TRADFRI」與「IKEA」是 Inter IKEA Systems B.V. 的商標；本專案為獨立作品，未經 IKEA 背書、贊助或關聯。它透過 gateway 自有的 CoAP/DTLS 介面溝通，若 IKEA 變更該介面可能會失效。
- **你的部署安全由你負責。** 本 server 會控制你家中的實體設備，並在網路上暴露設備名稱。為它設定安全措施——設定 `MCP_AUTH_TOKEN`、適當綁定、別放上公網——是你的責任。見 [Bearer 認證](#bearer-認證)。
- **非法律意見。**[資料與隱私](#資料與隱私) 一節為協助你思考自身情境的一般資訊，並非法律意見。若 GDPR 或其他法規適用於你的部署，請諮詢合格的專業人士。
