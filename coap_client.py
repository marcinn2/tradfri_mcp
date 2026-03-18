"""
aiocoap 封裝層：管理 CoAP context 的建立與 GET / PUT 操作。

Context 為 module-level singleton，首次呼叫時建立，之後共用。
aiocoap 的 Context 不是 thread-safe，但因為整個 server 跑在單一
asyncio event loop 上，這樣使用是安全的。
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
    """CoAP GET，回傳解析後的 JSON（dict 或 list）。"""
    global _ctx
    ctx = await get_ctx()
    uri = f"coaps://{GATEWAY_IP}{path}"
    req = aiocoap.Message(code=aiocoap.GET, uri=uri)
    try:
        res = await ctx.request(req).response
        return json.loads(res.payload)
    except Exception:
        _ctx = None
        raise


async def coap_put(path: str, payload: dict) -> None:
    """CoAP PUT，payload 為 dict，自動序列化為 JSON。"""
    global _ctx
    ctx = await get_ctx()
    uri = f"coaps://{GATEWAY_IP}{path}"
    req = aiocoap.Message(
        code    = aiocoap.PUT,
        uri     = uri,
        payload = json.dumps(payload).encode(),
    )
    req.opt.content_format = 50   # application/json
    try:
        await ctx.request(req).response
    except Exception:
        _ctx = None
        raise


async def shutdown() -> None:
    global _ctx
    if _ctx is not None:
        await _ctx.shutdown()
        _ctx = None
