"""
aiocoap 封裝層：管理 CoAP context 的建立與 GET / PUT 操作。

Context 為 module-level singleton，首次呼叫時建立，之後共用。
OBSERVE 訂閱與控制操作共用同一個 CoAP context（同一個 DTLS 連線），
因為 TRADFRI gateway 只允許每個 PSK identity 一個 DTLS session。

aiocoap 的 Context 不是 thread-safe，但因為整個 server 跑在單一
asyncio event loop 上，這樣使用是安全的。

Context 建立時使用 asyncio.Lock 避免多個 OBSERVE task 同時初始化而產生競爭。

重要：coap_put / coap_get 失敗時「不重置 context」。
OBSERVE 訂閱是 context 的 owner：OBSERVE 偵測到連線中斷後，才呼叫
reset_ctx() 清除舊 context，讓下次 get_ctx() 建立新的。
這樣可以避免控制操作失敗後破壞正在運作的 OBSERVE session。
若未設定 Telegram（無 OBSERVE），session 中斷後會等 OBSERVE 重試週期；
或手動呼叫 reset_ctx() 強制重建。
"""
import asyncio
import json
import aiocoap
import aiocoap.credentials

from config import GATEWAY_IP, PSK_FILE

_ctx: aiocoap.Context | None = None
_ctx_lock: asyncio.Lock | None = None


def _lock() -> asyncio.Lock:
    global _ctx_lock
    if _ctx_lock is None:
        _ctx_lock = asyncio.Lock()
    return _ctx_lock


async def get_ctx() -> aiocoap.Context:
    """取得（或建立）共用 CoAP context。使用 lock 避免並發初始化。"""
    global _ctx
    async with _lock():
        if _ctx is not None:
            return _ctx

        psk_data = json.loads(PSK_FILE.read_text())
        identity = psk_data["identity"]
        psk      = psk_data["psk"]

        ctx = await aiocoap.Context.create_client_context()
        ctx.client_credentials.load_from_dict({
            f"coaps://{GATEWAY_IP}/*": {
                "dtls": {
                    "psk":             psk.encode(),
                    "client-identity": identity.encode(),
                }
            }
        })
        _ctx = ctx
        return ctx


async def coap_get(path: str) -> dict | list:
    """CoAP GET，回傳解析後的 JSON（dict 或 list）。
    失敗時直接 raise，不重置 context（由 OBSERVE 負責 reset_ctx）。"""
    ctx = await get_ctx()
    uri = f"coaps://{GATEWAY_IP}{path}"
    req = aiocoap.Message(code=aiocoap.GET, uri=uri)
    res = await ctx.request(req).response
    return json.loads(res.payload)


async def coap_put(path: str, payload: dict) -> None:
    """CoAP PUT，payload 為 dict，自動序列化為 JSON。
    失敗時直接 raise，不重置 context（由 OBSERVE 負責 reset_ctx）。"""
    ctx = await get_ctx()
    uri = f"coaps://{GATEWAY_IP}{path}"
    req = aiocoap.Message(
        code    = aiocoap.PUT,
        uri     = uri,
        payload = json.dumps(payload).encode(),
    )
    req.opt.content_format = 50   # application/json
    await ctx.request(req).response


def reset_ctx() -> None:
    """清除 singleton context（由 OBSERVE task 在連線中斷後呼叫）。
    下次 get_ctx() 時重建新 context / 新 DTLS session。"""
    global _ctx
    _ctx = None


async def shutdown() -> None:
    global _ctx
    if _ctx is not None:
        try:
            await _ctx.shutdown()
        except Exception:
            pass
        _ctx = None
