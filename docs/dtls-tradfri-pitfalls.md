# 在 macOS 上透過 DTLS 連接 IKEA TRADFRI Gateway — 踩坑紀錄與修法

> **English summary:** This document records every pitfall encountered while establishing a DTLS + CoAP connection to an IKEA TRADFRI E1526 gateway on macOS using Python. Covers 9 issues including OpenSSL 3 AES-CCM incompatibility, macOS AF_INET6 socket behavior, TinyDTLS C source patches (sequence dedup reset, renegotiation_info bypass), pytradfri pydantic model incompatibility, and aiocoap credential URI formatting. Includes working minimal code examples and a complete debugging methodology appendix. The document is written in Traditional Chinese.

本文記錄了在 macOS 上以 Python 建立 DTLS + CoAP 連線至 TRADFRI E1526 gateway 所踩到的所有坑，以及每個坑的根本原因與解法。

**最終達成目標**：列出 gateway 下所有設備（燈具、插座、遙控器）、群組、場景，不依賴 pytradfri model 層。

**使用的函式庫**：[DTLSSocket 0.2.3](https://github.com/mclunis/DTLSSocket)（TinyDTLS 的 Cython 封裝）+ [aiocoap](https://github.com/chrysn/aiocoap)

目標讀者：想在 macOS 上寫自訂 TRADFRI client，但發現範例程式碼靜默失敗或一直 timeout 的開發者。

---

## 環境

| 元件 | 版本 / 說明 |
|------|------------|
| OS | macOS 15（Apple Silicon）|
| Python | 3.9（系統版，`/usr/bin/python3`）|
| DTLSSocket | 0.2.3（從原始碼 build）|
| TinyDTLS | 隨 DTLSSocket 附帶 |
| pytradfri | 最新 pip 版本 |
| aiocoap | 最新 pip 版本 |
| Gateway 型號 | IKEA TRADFRI E1526 |
| Gateway 韌體 | 1.21.x |

---

## #1 — OpenSSL 3 不支援 `TLS_PSK_WITH_AES_128_CCM_8`

### 症狀
使用 **libcoap**（例如 `coap-client` 或 aiocoap 的 libcoap backend）：

```
DTLS_ALERT_HANDSHAKE_FAILURE
```

握手在 cipher 協商階段立刻失敗。

### 根本原因
TRADFRI gateway 只支援兩組 DTLS cipher suite：
- `TLS_PSK_WITH_AES_128_CCM_8`（0xC0A8）
- `TLS_ECDHE_ECDSA_WITH_AES_128_CCM_8`（0xC0AC）

兩者都用 **AES-CCM**，而 OpenSSL 3.x 已將 AES-CCM 從預設 cipher provider 中移除。任何基於 OpenSSL 3 建置的 DTLS stack（Homebrew `libcoap`、aiocoap 的 libcoap backend 等）都無法完成握手。

### 解法
改用 **TinyDTLS**。TinyDTLS 是自包含的 C 函式庫，自帶 AES-CCM 實作，完全不依賴 OpenSSL。DTLSSocket 把 TinyDTLS 封裝成可從 Python 呼叫的 Cython extension。

---

## #2 — Cython 未執行導致 build 失敗

### 症狀
```
clang: error: no such file or directory: 'DTLSSocket/dtls.c'
```

### 根本原因
DTLSSocket 0.2.3 的 repo 只有 `dtls.pyx`，沒有預先編譯的 `dtls.c`。直接執行 `python setup.py develop` 時，編譯器找不到 `.c` 檔。

### 解法
先安裝 Cython，再手動將 `.pyx` 編譯成 `.c`，最後才 build：

```bash
pip3 install --user cython
~/.local/bin/cython DTLSSocket/dtls.pyx   # 產生 dtls.c
python3 setup.py develop --user            # 編譯 dtls.c → .so
```

> 注意：DTLSSocket 0.2.3 使用 `# cython: language_level=2`，Cython 3 會有警告但仍可正常 build。

---

## #3 — `APIFactory.generate_psk()` 靜默回傳 security code 原值

### 症狀
呼叫 `pytradfri` 的 `APIFactory.init(psk=SECURITY_CODE)` 後再呼叫 `generate_psk(SECURITY_CODE)`，回傳值等於 security code 本身。存入 PSK 檔的「psk」欄位實際上是 security code，後續連線全部失敗。

### 根本原因
`APIFactory` 內部邏輯：

```python
async def generate_psk(self, security_code):
    if not self._psk:       # ← 由這個判斷守門
        ...
    return self._psk        # ← 若 _psk 已設定則直接回傳，不發任何網路請求
```

呼叫 `APIFactory.init(host=..., psk_id=..., psk=SECURITY_CODE)` 會把 `self._psk` 設為 security code。`if not self._psk` 為 False，`generate_psk` 直接回傳 security code，根本沒有向 gateway 請求新的 PSK。

### 解法
打算產生新 PSK 時，`APIFactory.init` 的 `psk` 參數必須傳 `None`：

```python
factory = await APIFactory.init(host=GATEWAY_IP, psk_id=identity, psk=None)
psk = await factory.generate_psk(SECURITY_CODE)
```

---

## #4 — macOS 的 AF_INET6 socket 收不到 IPv4 UDP 回應

### 症狀
以 aiocoap（tinydtls transport）連接 IPv4 gateway：

```
aiocoap.error.ConRetransmitsExceeded
```

client 持續送出封包，但完全收不到任何回應——即使用 Wireshark / tcpdump 可以確認 gateway 有回應。

### 根本原因
DTLSSocket（以及 aiocoap 的 tinydtls transport）內部建立的是 **AF_INET6** socket，以 IPv4-mapped IPv6 格式（`::ffff:192.168.x.x`）傳遞位址。

在 **macOS** 上，kernel **不會**自動將 IPv4 UDP 回應解封裝後投遞給 AF_INET6 socket（Linux 會這樣做）。Gateway 回傳純 IPv4 UDP 封包，macOS 找不到對應的 socket，就靜默丟棄。

tcpdump 看得到 gateway 的回應，但 AF_INET6 socket 永遠收不到。

### 解法
手動建立 **AF_INET** socket 作為底層傳輸。在 `write_cb` 中，把 `::ffff:` 前綴去掉再呼叫 `sendto`：

```python
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(5)
sock.bind(('0.0.0.0', 0))

def write_cb(addr, data):
    host = addr[0].split('%')[0]
    if host.startswith('::ffff:'):
        host = host[7:]          # IPv4-mapped → 純 IPv4
    return sock.sendto(bytes(data), (host, addr[1]))
```

把 `sock.recvfrom` 收到的原始 bytes 回傳給 TinyDTLS 時，再加回 `::ffff:` 前綴：

```python
data, addr = sock.recvfrom(4096)
d.handleMessageAddr('::ffff:' + addr[0], addr[1], data)
```

---

## #5 — `Connection` 物件立即被 GC → 送出 `close_notify`

### 症狀
`d.connect(...)` 回傳後，TinyDTLS **立刻**送出 DTLS Alert `close_notify`（level=1 warning, desc=0），在 server 任何回應到達之前就關閉連線。

封包 trace：
```
SEND Handshake 77B   ← ClientHello
EVENT code=0x01DC    ← DTLS_EVENT_CONNECT 觸發
SEND Alert level=1 desc=0   ← close_notify！（不應該）
RECV 60B             ← ServerHello 姍姍來遲，已太晚
```

### 根本原因
`d.connect()` 回傳一個 `Connection` 物件。若回傳值未被變數接收，Python 立刻 GC 它。`Connection.__dealloc__` 呼叫 `dtls_reset_peer()`，後者呼叫 `dtls_destroy_peer(ctx, peer, DTLS_DESTROY_CLOSE)`，送出 `close_notify`。

`close_notify` 搶先 DTLS 握手送達，直接終止 session。

相關 Cython 程式碼（`dtls.pyx`）：
```python
cdef class Connection(Session):
    def __dealloc__(self):
        peer = tdtls.dtls_get_peer(self.d.ctx, &self.session)
        if peer:
            tdtls.dtls_reset_peer(self.d.ctx, peer)   # ← 送出 close_notify
```

### 解法
**一定要**把 `d.connect()` 的回傳值指派給變數，讓 `Connection` 存活：

```python
conn = d.connect('::ffff:192.168.x.x', 5684, 0, 0)   # ← 必須指派
```

---

## #6 — TinyDTLS 把 ServerHello 誤判為重複封包丟棄（record seq=0 碰撞）

### 症狀
收到 `HelloVerifyRequest`、送出帶 cookie 的第二個 `ClientHello` 後，握手卡住。`handle_handshake_msg` 從未被呼叫到 `ServerHello`。最終在 retransmit 的 `ServerHello` 抵達時，因狀態不對而觸發 handshake_failure。

加入 debug 後的 trace：
```
RECV 60B  hs=3  ← HelloVerifyRequest   (record seq=0, mseq=0)
SEND 109B hs=1  ← ClientHello+cookie
RECV 101B hs=2  ← ServerHello          (record seq=0, mseq=1)
  → 靜默丟棄！（去重機制認為 seq=0 已見過）
RECV 25B  hs=14 ← ServerHelloDone      (mseq=2，進 reorder buffer 等待）
RECV 101B hs=2  ← ServerHello retransmit (record seq=2, mseq=1)
  → 這次被處理，但狀態機已混亂
SEND Alert level=2 desc=40  ← handshake_failure
```

### 根本原因
TinyDTLS 用 **per-security-context 的 sequence number bitfield**（`security->cseq`）來偵測重複封包。`HelloVerifyRequest`（第一個 server flight）與 `ServerHello`（第二個 server flight）**都使用 record sequence number 0**，因為 gateway 在兩個 flight 之間重置了 record sequence counter。

`ServerHello`（seq=0）在 `HelloVerifyRequest`（seq=0）處理過後抵達：
```c
int64_t seqn_diff = pkt_seq_nr - security->cseq.cseq;  // = 0 - 0 = 0
if (seqn_diff == 0) {
    return 0;  // 丟棄：「重複封包」
}
```

`ServerHello` 被靜默丟棄。狀態機停在 `DTLS_STATE_CLIENTHELLO`。`ServerHelloDone`（mseq=2）因為 `mseq_r` 還停在 1，被放進 reorder buffer 等待。

### 修法（修改 TinyDTLS 原始碼 `dtls.c`）
在 `DTLS_HT_HELLO_VERIFY_REQUEST` 處理成功後，重置 sequence 去重狀態，讓 server 下一個 flight（從 seq=0 開始）不被誤殺：

```c
case DTLS_HT_HELLO_VERIFY_REQUEST:
    err = check_server_hello_verify_request(ctx, peer, data, data_length);
    if (err < 0) { ... }

    /* 重置 seq 去重：server 下一個 flight 的 record seq 從 0 重新開始 */
    dtls_security_params(peer)->cseq.bitfield = 0;

    break;
```

---

## #7 — TinyDTLS 預設強制要求 `renegotiation_info`，但 TRADFRI gateway 不送

### 症狀
修完 #5 和 #6 後，`check_server_hello` 仍然失敗，ServerHello 處理完就立刻送出 fatal alert，session 被關閉。

加入 debug 後：
```
DEBUG check_server_hello data_length=88
DEBUG dtls_check_tls_extension returned -552  ← fatal HANDSHAKE_FAILURE
```

`-552` 解碼為 `dtls_alert_fatal_create(DTLS_ALERT_HANDSHAKE_FAILURE)`
（`-(2 × 256 + 40) = -552`）。

### 根本原因
TinyDTLS 的 `default_user_parameters` 預設值：
```c
.force_extended_master_secret = 1,
.force_renegotiation_info     = 1,
```

`dtls_check_tls_extension` 裡的 `check_forced_extensions` 會驗證兩者。TRADFRI gateway 的 `ServerHello` **不包含** `renegotiation_info` extension（0xFF01）。Gateway 是透過在 `ClientHello` 的 cipher list 裡接受 `TLS_EMPTY_RENEGOTIATION_INFO_SCSV` 偽 cipher 來符合 RFC 5746，但不在 `ServerHello` 中回應這個 extension。

`force_renegotiation_info = 1` 且 `config->renegotiation_info == 0` 時：
```c
if (config->user_parameters.force_renegotiation_info) {
    if (!config->renegotiation_info) {
        goto error;   // → DTLS_ALERT_HANDSHAKE_FAILURE
    }
}
```

### 修法（修改 TinyDTLS 原始碼 `dtls.c`）
將 `default_user_parameters` 的兩個強制檢查都關閉：

```c
static const dtls_user_parameters_t default_user_parameters = {
    ...
    .force_extended_master_secret = 0,   // 原本是 1
    .force_renegotiation_info     = 0,   // 原本是 1
};
```

> Gateway 確實有送 `extended_master_secret` extension（0x0017），所以那個
> 檢查本來就會過。連接已知且可信的本地 gateway 時，兩個都設為 0 是安全的。

---

## #8 — pytradfri 最新版與 gateway 韌體 1.21.x 的 pydantic 不相容

### 症狀
使用 `pip install pytradfri` 安裝最新版，執行任何 device 列舉時拋出：

```
pydantic.error_wrappers.ValidationError: N validation errors
  - field required (type=value_error.missing)  ← 欄位如 15025, 15015, 3.3, 3.9
```

或（pydantic v2）：

```
pydantic_core._pydantic_core.ValidationError: N validation errors for ...
  15025
    Field required [type=missing, ...]
```

### 根本原因
pytradfri 的最新版本把 gateway 回傳的原始 JSON 透過 pydantic model 解析，而這些 model 是針對較新韌體設計的，包含 gateway 韌體 1.21.x **不會回傳**的欄位（如 `15025`、`15015`、`3.3`、`3.9`）。

pydantic 預設情況下 `Field required` 表示必填欄位缺失，整個 model 解析直接失敗，沒有 fallback。

### 解法
**完全放棄 pytradfri 的 model 層**，改用 aiocoap 直接送 CoAP GET，並自行以 dict key 解析 JSON 回應：

```python
import aiocoap, json

ctx = await aiocoap.Context.create_client_context()
# ... 載入 credentials（見 #9）

async def get(ctx, path):
    uri = f"coaps://{GATEWAY_IP}{path}"
    req = aiocoap.Message(code=aiocoap.GET, uri=uri)
    res = await ctx.request(req).response
    return json.loads(res.payload)

device_ids = await get(ctx, "/15001")
for did in device_ids:
    d = await get(ctx, f"/15001/{did}")
    name = d.get("9001")   # KEY_NAME
    # ...
```

Gateway 的 CoAP key 為純整數字串（`"9001"`、`"5850"` 等），直接取 dict key 即可，不依賴任何 model 驗證。

---

## #9 — aiocoap credentials URI 不能帶 port 號

### 症狀
用 `ctx.client_credentials.load_from_dict()` 設定 PSK 憑證時，CoAP 請求拋出：

```
aiocoap.error.CredentialsMissingError:
  No suitable credentials for coaps://192.168.x.x/15001
```

即使 PSK 正確、位址正確，每次都失敗。

### 根本原因
`load_from_dict` 的 key 是用來匹配請求 URI 的 glob pattern。設定：

```python
ctx.client_credentials.load_from_dict({
    "coaps://192.168.x.x:5684/*": { ... }   # ← 帶了 :5684
})
```

但 aiocoap 內部構造的請求 URI 是 `coaps://192.168.x.x/15001`（預設 port 5684 不會寫進 URI）。兩者不匹配，找不到憑證。

### 解法
credential key 的 URI **不要帶 port**：

```python
ctx.client_credentials.load_from_dict({
    f"coaps://{GATEWAY_IP}/*": {    # ← 不帶 port
        "dtls": {
            "psk":             psk.encode(),
            "client-identity": identity.encode(),
        }
    }
})
```

aiocoap 的 URI 匹配規則：只有當請求 URI 與 credential key pattern 的 scheme、host、port（或 scheme 預設 port）和 path 全部對上，才算命中。`coaps` 的預設 port 是 5684，所以 `coaps://host/*` 會匹配 `coaps://host/path`，但 `coaps://host:5684/*` 不會。

---

## 所有修改一覽

| # | 檔案 | 修改內容 |
|---|------|---------|
| 1 | `dtls.c` | `check_server_hello_verify_request` 後加 `cseq.bitfield = 0` |
| 2 | `dtls.c` | `default_user_parameters` 的 `force_extended_master_secret` 與 `force_renegotiation_info` 改為 0 |
| 3 | 呼叫端程式碼 | `conn = d.connect(...)` 必須指派，防止 GC 觸發 `close_notify` |
| 4 | 呼叫端程式碼 | 使用 AF_INET socket，`write_cb` 去除 `::ffff:` 前綴（macOS 專用）|

---

## 可運作的最小 DTLS 握手範例

```python
import socket
from DTLSSocket import dtls
from DTLSSocket.dtls import Session

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(5)
sock.bind(('0.0.0.0', 0))

GATEWAY_IP    = "192.168.x.x"
GATEWAY_PORT  = 5684
SECURITY_CODE = b"<16 位 Security Code>"

received_data = []

def write_cb(addr, data):
    host = addr[0].split('%')[0]
    if host.startswith('::ffff:'):
        host = host[7:]
    return sock.sendto(bytes(data), (host, addr[1]))

def read_cb(addr, data):
    received_data.append(bytes(data))
    return len(data)

def event_cb(level, code):
    if code == 0x01DE:
        print("DTLS 握手完成")

d = dtls.DTLS(
    read=read_cb, write=write_cb, event=event_cb,
    pskId=b"Client_identity",
    pskStore={b"Client_identity": SECURITY_CODE, b"": SECURITY_CODE},
)
conn = d.connect(f'::ffff:{GATEWAY_IP}', GATEWAY_PORT, 0, 0)  # 必須指派！

for _ in range(10):
    try:
        data, addr = sock.recvfrom(4096)
        d.handleMessageAddr(f'::ffff:{addr[0]}', addr[1], data)
        if received_data:   # read_cb 被呼叫 = 應用層資料到了
            break
    except socket.timeout:
        break
```

---

## PSK 產生（在 DTLS session 上送 CoAP POST）

握手以 `Client_identity` + security code 完成後，透過 CoAP POST 註冊永久 identity：

```
POST coaps://192.168.x.x:5684/15011/9063
Content-Format: application/json
{"9090": "<自訂 identity 名稱>"}

→ 2.01 Created
{"9091": "<產生的 PSK>", "9029": "1.21.xxxx"}
```

把回傳的 identity + PSK 存起來，之後所有連線都用這組，不再使用 `Client_identity` + security code。

---

## 最終可運作的完整方案

**目標**：列出 gateway 下所有設備、群組、場景。

**採用方案**：
- DTLS 握手與 PSK 產生：手動用 DTLSSocket（修補過的 TinyDTLS），搭配 AF_INET socket（繞過 macOS 的 AF_INET6 限制）
- 設備列舉：aiocoap `Context.create_client_context()` + `load_from_dict()` 直接發 CoAP GET，自行解析 JSON key
- **完全不使用 pytradfri 的 model 層**（因 #8 的 pydantic 不相容）

這個方案：
- 不需要修改 aiocoap 本體
- 不依賴 pytradfri 的 pydantic model
- DTLS PSK 只需產生一次，存入 JSON 檔後反覆使用

## 關於 pytradfri / aiocoap 在 macOS 的整合說明（歷史記錄）

`pytradfri` 透過 `aiocoap` 連線，`aiocoap` 有自己的 tinydtls transport（`aiocoap.transports.tinydtls`）。該 transport 內部建立自己的 DTLSSocket，使用 AF_INET6 socket，在 macOS 上會踩到 **#4**（IPv4 回應收不到）。

即使解決了 #4，pytradfri 的 model 層仍會因 **#8**（pydantic 欄位不相容）而失敗。最終選擇完全繞過 pytradfri，採用上述方案。

若要繼續使用 pytradfri 路線，可考慮：
1. **修改 aiocoap 的 tinydtls transport**，改用 AF_INET + 純 IPv4 位址。
2. **pin pytradfri 到較舊版本**，或 patch model 去掉 required 欄位的強制驗證。
3. **改在 Linux 上執行**，Linux 的 AF_INET6 / IPv4-mapped 行為正常，不需要特別處理 #4。

---

*測試對象：TRADFRI gateway 韌體 1.21.0051*

---

## 附錄 — 除錯的思路與過程

這份附錄記錄的不是「答案」，而是「怎麼找到答案」。每個問題的第一個症狀通常只有一句錯誤訊息，後面的偵查過程才是真正費時的地方。

### 第一階段：選擇 DTLS 函式庫

最初嘗試用 aiocoap 的預設 backend（libcoap），直接拿 pytradfri 範例跑，得到 `DTLS_ALERT_HANDSHAKE_FAILURE`。

第一直覺是「PSK 或位址填錯了」，花了一些時間確認參數都對之後，開始往 cipher 方向想。用 `openssl ciphers` 列舉 OpenSSL 3 支援的清單，找不到 `TLS_PSK_WITH_AES_128_CCM_8`。查了 OpenSSL changelog 確認 AES-CCM 在 3.0 被移出 default provider。這才意識到這不是設定問題，而是 **函式庫根本不支援這個 cipher**。

從這裡轉向 TinyDTLS / DTLSSocket。

### 第二階段：確認封包真的有收到

DTLSSocket 裝好後，aiocoap 仍然 timeout（`ConRetransmitsExceeded`）。此時有兩個可能：一是程式設定錯，二是封包根本沒到達或沒被收到。

**關鍵動作：開 tcpdump 看封包。**

```bash
tcpdump -i any udp port 5684
```

tcpdump 清楚看到：client 送出 ClientHello、gateway 回了 HelloVerifyRequest，但 Python 程式完全沒反應。這排除了「gateway 不通」的可能，問題一定在 socket 的接收層。

接著寫了一個最小測試，繞過 aiocoap，直接用 `socket.recvfrom` 接收，發現 AF_INET socket 能收到回應，AF_INET6 收不到。在 macOS 上驗證了 IPv4-mapped 行為與 Linux 不同的假設。

### 第三階段：close_notify 搶先送出

解決了 socket 問題後，用自己的 AF_INET socket 搭配 DTLSSocket，第一次看到 ClientHello 真的被送出去，也收到了 HelloVerifyRequest。但緊接著 **在收到任何 server 回應之前**，DTLSSocket 自己送出了 `close_notify`。

這很反直覺。ClientHello 剛出去，握手根本還沒開始，為什麼要關連線？

首先懷疑是 event callback 裡的程式碼觸發了什麼，但 callback 只有一行 print，不可能。接著想到：**也許不是主動行為，而是解構子**。

翻了 `dtls.pyx` 的 `Connection` class，看到 `__dealloc__` 呼叫 `dtls_reset_peer`，而 `dtls_reset_peer` 的實作是：

```c
void dtls_reset_peer(...) {
    dtls_destroy_peer(ctx, peer, DTLS_DESTROY_CLOSE);
}
```

`DTLS_DESTROY_CLOSE` 會送出 `close_notify`。再往上追：`d.connect()` 的回傳值在測試程式裡沒有被接收，Python 立刻 GC `Connection` 物件。整條鏈清楚了。

### 第四階段：握手卡在 ServerHello 之後

修完 close_notify 之後，握手有更多進展，但最終仍以 `handshake_failure` 結束，而且 PSK callback 從未被呼叫。這代表狀態機根本沒走到 ClientKeyExchange 那一步。

此時的 trace 看起來像：
```
← HelloVerifyRequest
→ ClientHello+cookie
← ServerHello          （沒有觸發任何 callback）
← ServerHelloDone      （沒有觸發任何 callback）
← ServerHello retransmit
→ Alert handshake_failure
```

**第一個懷疑：PSK callback 被呼叫但沒有印出來。** 重新確認 stderr 有合併，確認 .so 有重新 build，沒有問題。

**第二個懷疑：peer 根本沒被找到。** 在 `dtls_handle_message` 裡加了 `fprintf(stderr, "PEER FOUND/NOT FOUND")`，結果每次都是 FOUND，排除。

**第三個懷疑：`handle_handshake_msg` 根本沒被呼叫。** 在函式入口加了 debug print，發現 ServerHello 和 ServerHelloDone 都**沒有**觸發這個函式，只有 HelloVerifyRequest 和後來的 retransmit ServerHello 有。

這讓問題變得很具體：**為什麼同樣是封包、同樣找得到 peer，有的封包能進 `handle_handshake_msg`，有的不行？**

中間還有什麼過濾機制？往上查呼叫路徑，找到了 sequence deduplication 的邏輯。手動解碼 HelloVerifyRequest 和 ServerHello 的 record header，發現兩者的 **record sequence number 都是 0**。

```python
hvr_seq = int.from_bytes(hvr_bytes[5:11], 'big')   # → 0
sh_seq  = int.from_bytes(sh_bytes[5:11],  'big')   # → 0（！）
```

這才有了完整解釋：gateway 在兩個 flight 之間重置了 record sequence counter，而 TinyDTLS 的去重機制沒有意識到這是兩個不同的 flight。

### 第五階段：ServerHello 被處理但仍然失敗

加了 `cseq.bitfield = 0` 的修法後，ServerHello 終於進入 `handle_handshake_msg`，但立刻回傳錯誤，仍然沒有送出 ClientKeyExchange。

在 `check_server_hello` 的出口加了 debug，印出 `dtls_check_tls_extension` 的回傳值：`-552`。

解碼 `-552`：`-(2 × 256 + 40)`，對照 TinyDTLS 的 alert code 表，`40 = 0x28 = DTLS_ALERT_HANDSHAKE_FAILURE`，level 2 = fatal。

`dtls_check_tls_extension` 回傳 HANDSHAKE_FAILURE 的地方只有一個 `error:` label，往回追看哪個 `goto error` 被觸發。用 debug print 縮小到 `check_forced_extensions`，看到兩個 force 檢查：`force_extended_master_secret` 與 `force_renegotiation_info`。

手動解碼 ServerHello 的 extension list（最後 6 bytes：`00 04 00 17 00 00`），只有 `0x0017`（extended_master_secret），沒有 `0xFF01`（renegotiation_info）。

確認了就是 `force_renegotiation_info` 的檢查在踢人。查 RFC 5746，理解 gateway 用 `TLS_EMPTY_RENEGOTIATION_INFO_SCSV` 替代 extension 的做法是合法的，TinyDTLS 的強制要求過於嚴格。

### 除錯方法總結

這次除錯過程用到的關鍵技術：

1. **tcpdump 優先**：在懷疑任何函式庫行為之前，先確認封包層面的事實。「gateway 有沒有回應」這個問題要在網路層確認，不要依賴函式庫的 timeout 訊息。

2. **在 C 原始碼加 `fprintf(stderr, ...)`**：TinyDTLS 的 `dtls_set_log_level` 產生的 log 不夠細，遇到無法解釋的行為時，直接在懷疑的函式入口加 `fprintf` 再重新 build，是最快的確認方式。

3. **手動解碼封包 bytes**：DTLS record header 和 handshake header 格式固定，用 Python 幾行就能解出 record seq、handshake type、message seq。遇到「為什麼這個封包沒被處理」的問題，先解碼再對照原始碼，比 strace 直覺很多。

4. **追 GC 導致的副作用**：Python 呼叫 C extension 時，物件的 dealloc 可能觸發 C 層的副作用（如送出網路封包）。碰到「我沒叫它做這件事，它自己做了」的情況，優先懷疑 GC timing。

5. **把錯誤碼解碼成有意義的值**：TinyDTLS 的函式回傳值是 `-(level * 256 + code)` 的編碼形式，直接看 `-552` 沒意義，但解碼成 `(2, 40)` → `(fatal, handshake_failure)` 後馬上知道方向。
