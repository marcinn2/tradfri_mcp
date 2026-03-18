#!/usr/bin/env python3
"""
TRADFRI gateway 掃描 — 直接用 aiocoap 發 CoAP GET，不依賴 pytradfri model 解析
用法: python3 scripts/scan.py
環境變數:
  TRADFRI_GATEWAY_IP  — gateway IP（必填）
  PSK_FILE            — PSK 憑證路徑（預設 .tradfri_psk.json）
"""
import asyncio, json, os, sys
import aiocoap
import aiocoap.credentials

GATEWAY_IP = os.environ.get("TRADFRI_GATEWAY_IP", "")
PSK_FILE   = os.environ.get("PSK_FILE", ".tradfri_psk.json")

if not GATEWAY_IP:
    print("ERROR: 請設定 TRADFRI_GATEWAY_IP 環境變數", file=sys.stderr)
    sys.exit(1)

KEY_NAME       = "9001"
KEY_ID         = "9003"
KEY_TYPE       = "5750"
KEY_REACHABLE  = "9019"
KEY_LIGHT      = "3311"
KEY_PLUG       = "3312"
KEY_DIMMER     = "5851"
KEY_STATE      = "5850"
KEY_COLOR_TEMP = "5711"
KEY_COLOR_HEX  = "5706"
KEY_MEMBERS    = "9018"

APP_TYPE = {0: "remote", 2: "light", 3: "plug", 4: "blind", 6: "repeater"}

async def get(ctx, path):
    uri = f"coaps://{GATEWAY_IP}{path}"
    req = aiocoap.Message(code=aiocoap.GET, uri=uri)
    res = await ctx.request(req).response
    return json.loads(res.payload)

async def main():
    with open(PSK_FILE) as f:
        psk_data = json.load(f)
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

    # ── 設備 ───────────────────────────────────────────────────────────────
    print("=" * 60)
    print("DEVICES")
    print("=" * 60)

    device_ids = await get(ctx, "/15001")
    for did in device_ids:
        d = await get(ctx, f"/15001/{did}")

        info = {
            "id":        d.get(KEY_ID),
            "name":      d.get(KEY_NAME),
            "type":      APP_TYPE.get(d.get(KEY_TYPE), d.get(KEY_TYPE)),
            "reachable": bool(d.get(KEY_REACHABLE, 0)),
        }

        if KEY_LIGHT in d:
            info["lights"] = []
            for light in d[KEY_LIGHT]:
                info["lights"].append({
                    "state":      bool(light.get(KEY_STATE, 0)),
                    "brightness": light.get(KEY_DIMMER),
                    "color_temp": light.get(KEY_COLOR_TEMP),
                    "color":      light.get(KEY_COLOR_HEX),
                })

        if KEY_PLUG in d:
            plugs = d[KEY_PLUG]
            info["socket_state"] = bool(plugs[0].get(KEY_STATE, 0)) if plugs else None

        print(json.dumps(info, ensure_ascii=False, indent=2))

    # ── 群組 ───────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("GROUPS")
    print("=" * 60)

    group_ids = await get(ctx, "/15004")
    groups = []
    for gid in group_ids:
        g = await get(ctx, f"/15004/{gid}")
        groups.append(g)

        members_raw = g.get(KEY_MEMBERS, {})
        member_ids  = members_raw.get("15002", {}).get("9003", []) if isinstance(members_raw, dict) else []

        info = {
            "id":         g.get(KEY_ID),
            "name":       g.get(KEY_NAME),
            "state":      bool(g.get(KEY_STATE, 0)),
            "brightness": g.get(KEY_DIMMER),
            "member_ids": member_ids,
        }
        print(json.dumps(info, ensure_ascii=False, indent=2))

    # ── Scenes ────────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("SCENES PER GROUP")
    print("=" * 60)

    for g in groups:
        gid  = g.get(KEY_ID)
        name = g.get(KEY_NAME)
        try:
            scene_ids = await get(ctx, f"/15005/{gid}")
            print(f"\nGroup '{name}' (id={gid}):")
            for sid in scene_ids:
                s = await get(ctx, f"/15005/{gid}/{sid}")
                print(f"  id={sid}  name={s.get(KEY_NAME, '?')}")
        except Exception as e:
            print(f"\nGroup '{name}' (id={gid}): (no scenes: {e})")

    await ctx.shutdown()

asyncio.run(main())
