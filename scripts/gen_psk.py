#!/usr/bin/env python3
"""
TRADFRI PSK 產生器 — 用 security code 向 gateway 申請長期 PSK 憑證
用法: python3 scripts/gen_psk.py
環境變數:
  TRADFRI_GATEWAY_IP    — gateway IP（必填）
  TRADFRI_SECURITY_CODE — gateway 背面標籤上的 Security Code（必填）
  PSK_FILE              — 輸出路徑（預設 .tradfri_psk.json）

原理:
  1. 以 Client_identity + security_code 完成 DTLS 握手（一次性）
  2. 向 /15011/9063 發 CoAP POST，取得長期 identity + PSK
  3. 存入 PSK_FILE

需要修補過的 TinyDTLS（macOS）— 詳見 docs/dtls-tradfri-pitfalls.md
"""
import asyncio, json, os, socket, sys, time, uuid

try:
    import aiocoap
    import aiocoap.credentials
except ImportError:
    print("ERROR: 請先執行 uv sync 安裝依賴", file=sys.stderr)
    sys.exit(1)

GATEWAY_IP    = os.environ.get("TRADFRI_GATEWAY_IP", "")
SECURITY_CODE = os.environ.get("TRADFRI_SECURITY_CODE", "")
PSK_FILE      = os.environ.get("PSK_FILE", ".tradfri_psk.json")

if not GATEWAY_IP:
    print("ERROR: 請設定 TRADFRI_GATEWAY_IP 環境變數", file=sys.stderr)
    sys.exit(1)

if not SECURITY_CODE:
    print("ERROR: 請設定 TRADFRI_SECURITY_CODE 環境變數", file=sys.stderr)
    sys.exit(1)

# PSK 產生端點（TRADFRI CoAP 路徑）
IDENTITY_ENDPOINT = "/15011/9063"
KEY_NEW_PSK       = "9091"   # server 回傳的新 PSK
KEY_FIRMWARE      = "9029"   # gateway 韌體版本

async def generate_psk():
    """用 security code 向 gateway 申請長期 PSK。"""
    new_identity = f"kc-tradfri-{uuid.uuid4().hex[:8]}"

    print(f"Gateway IP:   {GATEWAY_IP}")
    print(f"New identity: {new_identity}")
    print(f"PSK file:     {PSK_FILE}")
    print()

    # 用 security code 作為一次性 PSK 連線
    ctx = await aiocoap.Context.create_client_context()
    ctx.client_credentials.load_from_dict({
        f"coaps://{GATEWAY_IP}/*": {
            "dtls": {
                "psk":             SECURITY_CODE.encode(),
                "client-identity": b"Client_identity",
            }
        }
    })

    # POST /15011/9063 請求新 PSK
    payload = json.dumps({"9090": new_identity}).encode()
    uri     = f"coaps://{GATEWAY_IP}{IDENTITY_ENDPOINT}"

    print(f"POST {uri}")
    req = aiocoap.Message(
        code=aiocoap.POST,
        uri=uri,
        payload=payload,
        content_format=aiocoap.numbers.media_types_rev["application/json"],
    )

    try:
        res = await ctx.request(req).response
    except Exception as e:
        print(f"ERROR: CoAP 請求失敗 — {e}", file=sys.stderr)
        print()
        print("常見原因：")
        print("  • SECURITY_CODE 填錯（請對照 gateway 背面標籤）")
        print("  • macOS + DTLSSocket 需要 patch TinyDTLS — 見 docs/dtls-tradfri-pitfalls.md")
        await ctx.shutdown()
        sys.exit(1)

    if res.code.is_successful():
        data     = json.loads(res.payload)
        new_psk  = data.get(KEY_NEW_PSK, "")
        firmware = data.get(KEY_FIRMWARE, "unknown")

        if not new_psk:
            print(f"ERROR: server 回傳資料中找不到 PSK（key 9091）: {data}", file=sys.stderr)
            await ctx.shutdown()
            sys.exit(1)

        result = {"identity": new_identity, "psk": new_psk}
        with open(PSK_FILE, "w") as f:
            json.dump(result, f, indent=2)
            f.write("\n")

        print(f"✓ DTLS 握手完成，gateway 韌體：{firmware}")
        print(f"✓ PSK 已存入 {PSK_FILE}")
        print(f"  identity: {new_identity}")
        print(f"  psk:      {new_psk[:4]}{'*' * (len(new_psk) - 4)}")
    else:
        print(f"ERROR: server 回傳非成功碼 {res.code}: {res.payload}", file=sys.stderr)
        await ctx.shutdown()
        sys.exit(1)

    await ctx.shutdown()

asyncio.run(generate_psk())
