"""
aiocoap wrapper: manages CoAP context creation and GET / PUT operations.

Context is a module-level singleton, created on first call and shared thereafter.
All operations share one CoAP context (one DTLS session) because the TRADFRI gateway
allows only one DTLS session per PSK identity.

aiocoap Context is not thread-safe, but since the entire server runs on a single
asyncio event loop this usage is safe.

Important: coap_put / coap_get do NOT reset the context on failure.
Call reset_ctx() explicitly to force a new DTLS session on the next request.
"""
import asyncio
import json
import logging
import aiocoap
import aiocoap.credentials

from config import GATEWAY_IP, PSK_FILE

_log = logging.getLogger("coap")
COAP_TIMEOUT = 8.0  # seconds before a CoAP request is abandoned

_ctx: aiocoap.Context | None = None
_ctx_lock: asyncio.Lock | None = None


def _lock() -> asyncio.Lock:
    global _ctx_lock
    if _ctx_lock is None:
        _ctx_lock = asyncio.Lock()
    return _ctx_lock


async def get_ctx() -> aiocoap.Context:
    """Get (or create) the shared CoAP context. Uses a lock to prevent concurrent init."""
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
    """CoAP GET, returns parsed JSON (dict or list).
    Raises on timeout or non-success; resets context on timeout."""
    ctx = await get_ctx()
    uri = f"coaps://{GATEWAY_IP}{path}"
    req = aiocoap.Message(code=aiocoap.GET, uri=uri)
    try:
        res = await asyncio.wait_for(ctx.request(req).response, timeout=COAP_TIMEOUT)
    except asyncio.TimeoutError:
        _log.warning("CoAP GET %s timed out — resetting context", path)
        reset_ctx()
        raise RuntimeError(f"CoAP GET {path} timed out after {COAP_TIMEOUT}s")
    if not res.code.is_successful():
        raise RuntimeError(f"CoAP GET {path} failed: {res.code}")
    if not res.payload:
        return {}
    return json.loads(res.payload)


async def coap_put(path: str, payload: dict) -> None:
    """CoAP PUT, payload is a dict serialized to JSON.
    Raises on timeout or failure; resets context on timeout."""
    ctx = await get_ctx()
    uri = f"coaps://{GATEWAY_IP}{path}"
    req = aiocoap.Message(
        code    = aiocoap.PUT,
        uri     = uri,
        payload = json.dumps(payload).encode(),
    )
    req.opt.content_format = 50   # application/json
    try:
        await asyncio.wait_for(ctx.request(req).response, timeout=COAP_TIMEOUT)
    except asyncio.TimeoutError:
        _log.warning("CoAP PUT %s timed out — resetting context", path)
        reset_ctx()
        raise RuntimeError(f"CoAP PUT {path} timed out after {COAP_TIMEOUT}s")


def reset_ctx() -> None:
    """Clear the singleton context. The next get_ctx() creates a new DTLS session."""
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
