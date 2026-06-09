#!/usr/bin/env python3
"""
TRADFRI PSK generator — requests a long-term PSK from the gateway using the security code
Usage: python3 scripts/gen_psk.py
Env vars:
  TRADFRI_GATEWAY_IP    — gateway IP (required)
  TRADFRI_SECURITY_CODE — Security Code from the label on the back of the gateway (required)
  PSK_FILE              — output path (default .tradfri_psk.json)

How it works:
  1. Complete a one-time DTLS handshake using Client_identity + security_code
  2. CoAP POST to /15011/9063 to obtain a long-term identity + PSK
  3. Save to PSK_FILE

Requires patched TinyDTLS (macOS) — see docs/dtls-tradfri-pitfalls.md
"""
import asyncio, json, os, sys, uuid

try:
    import aiocoap
    import aiocoap.credentials
except ImportError:
    print("ERROR: run 'uv sync' to install dependencies first", file=sys.stderr)
    sys.exit(1)

GATEWAY_IP    = os.environ.get("TRADFRI_GATEWAY_IP", "")
SECURITY_CODE = os.environ.get("TRADFRI_SECURITY_CODE", "")
PSK_FILE      = os.environ.get("PSK_FILE", ".tradfri_psk.json")

if not GATEWAY_IP:
    print("ERROR: set TRADFRI_GATEWAY_IP", file=sys.stderr)
    sys.exit(1)

if not SECURITY_CODE:
    print("ERROR: set TRADFRI_SECURITY_CODE", file=sys.stderr)
    sys.exit(1)

# PSK generation endpoint (TRADFRI CoAP path)
IDENTITY_ENDPOINT = "/15011/9063"
KEY_NEW_PSK       = "9091"   # new PSK returned by the server
KEY_FIRMWARE      = "9029"   # gateway firmware version

async def generate_psk():
    """Request a long-term PSK from the gateway using the security code."""
    new_identity = f"tradfri-{uuid.uuid4().hex[:8]}"

    print(f"Gateway IP:   {GATEWAY_IP}")
    print(f"New identity: {new_identity}")
    print(f"PSK file:     {PSK_FILE}")
    print()

    # use security code as a one-time PSK for the initial handshake
    ctx = await aiocoap.Context.create_client_context()
    ctx.client_credentials.load_from_dict({
        f"coaps://{GATEWAY_IP}/*": {
            "dtls": {
                "psk":             SECURITY_CODE.encode(),
                "client-identity": b"Client_identity",
            }
        }
    })

    # POST /15011/9063 to request a new PSK
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
        print(f"ERROR: CoAP request failed — {e}", file=sys.stderr)
        print()
        print("Common causes:")
        print("  • wrong SECURITY_CODE (check the label on the back of the gateway)")
        print("  • macOS + DTLSSocket requires patched TinyDTLS — see docs/dtls-tradfri-pitfalls.md")
        await ctx.shutdown()
        sys.exit(1)

    if res.code.is_successful():
        data     = json.loads(res.payload)
        new_psk  = data.get(KEY_NEW_PSK, "")
        firmware = data.get(KEY_FIRMWARE, "unknown")

        if not new_psk:
            print(f"ERROR: PSK not found in server response (key 9091): {data}", file=sys.stderr)
            await ctx.shutdown()
            sys.exit(1)

        result = {"identity": new_identity, "psk": new_psk}
        with open(PSK_FILE, "w") as f:
            json.dump(result, f, indent=2)
            f.write("\n")

        print(f"✓ DTLS handshake complete, gateway firmware: {firmware}")
        print(f"✓ PSK saved to {PSK_FILE}")
        print(f"  identity: {new_identity}")
        print(f"  psk:      {new_psk[:4]}{'*' * (len(new_psk) - 4)}")
    else:
        print(f"ERROR: non-success response {res.code}: {res.payload}", file=sys.stderr)
        await ctx.shutdown()
        sys.exit(1)

    await ctx.shutdown()

asyncio.run(generate_psk())
