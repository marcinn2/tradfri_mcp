"""
設備拓撲管理：讀寫 devices.json 與 aliases.json。

devices.json 由 refresh() 產生，aliases.json 由 user 手動維護。
"""
import json
from typing import Optional
from config import DEVICES_FILE, ALIASES_FILE

# ── CoAP key 常數 ──────────────────────────────────────────────────────────

KEY_NAME       = "9001"
KEY_ID         = "9003"
KEY_TYPE       = "5750"
KEY_REACHABLE  = "9019"
KEY_LIGHT      = "3311"
KEY_PLUG       = "3312"
KEY_STATE      = "5850"
KEY_DIMMER     = "5851"
KEY_COLOR_TEMP = "5711"
KEY_COLOR_X    = "5709"
KEY_COLOR_Y    = "5710"
KEY_MEMBERS    = "9018"

APP_TYPE = {0: "remote", 2: "light", 3: "plug", 4: "blind", 6: "repeater"}

# CIE XY 色彩對照表（已 scale 到 0–65535）
COLOR_MAP: dict[str, tuple[int, int]] = {
    "red":        (45914, 19661),
    "green":      (19661, 45914),
    "blue":       (9830,  3932),
    "orange":     (42163, 25887),
    "yellow":     (37449, 37449),
    "warm_white": (30140, 26870),
    "cool_white": (24115, 26053),
    "purple":     (21043, 9830),
    "pink":       (39321, 16711),
}

MIRED_MIN = 250   # ~4000K 冷白
MIRED_MAX = 454   # ~2200K 暖白


# ── devices.json 讀寫 ──────────────────────────────────────────────────────

def load_devices() -> dict:
    """載入 devices.json。若不存在回傳空結構。"""
    if not DEVICES_FILE.exists():
        return {"devices": [], "groups": [], "scenes": {}}
    return json.loads(DEVICES_FILE.read_text())


def save_devices(data: dict) -> None:
    DEVICES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


# ── aliases.json 讀寫 ──────────────────────────────────────────────────────

def load_aliases() -> dict:
    """載入 aliases.json。若不存在回傳空 dict。"""
    if not ALIASES_FILE.exists():
        return {}
    return json.loads(ALIASES_FILE.read_text())


# ── 名稱解析 ───────────────────────────────────────────────────────────────

def resolve(name: str) -> Optional[dict]:
    """
    將 alias 或設備名稱解析為 {"type": "group"|"device", "id": int}。
    優先查 aliases.json，再做 devices.json 名稱模糊匹配。
    """
    aliases = load_aliases()

    # 完全匹配 alias
    if name in aliases:
        return aliases[name]

    # 大小寫不敏感匹配
    name_lower = name.lower()
    for key, val in aliases.items():
        if key.lower() == name_lower:
            return val

    # fallback：devices.json 名稱匹配
    data = load_devices()
    for g in data.get("groups", []):
        if g.get("name", "").lower() == name_lower:
            return {"type": "group", "id": g["id"]}
    for d in data.get("devices", []):
        if d.get("name", "").lower() == name_lower:
            return {"type": "device", "id": d["id"]}

    return None


# ── 掃描結果解析 ──────────────────────────────────────────────────────────

def parse_device(raw: dict) -> dict:
    info: dict = {
        "id":        raw.get(KEY_ID),
        "name":      raw.get(KEY_NAME),
        "type":      APP_TYPE.get(raw.get(KEY_TYPE), str(raw.get(KEY_TYPE))),
        "reachable": bool(raw.get(KEY_REACHABLE, 0)),
    }
    if KEY_LIGHT in raw:
        lights = raw[KEY_LIGHT]
        if lights:
            light = lights[0]
            info["state"]      = bool(light.get(KEY_STATE, 0))
            info["brightness"] = light.get(KEY_DIMMER)
            info["color_temp"] = light.get(KEY_COLOR_TEMP)
            info["color_x"]    = light.get(KEY_COLOR_X)
            info["color_y"]    = light.get(KEY_COLOR_Y)
            # capabilities
            info["supports_color_temp"]  = KEY_COLOR_TEMP in light
            info["supports_color"]       = KEY_COLOR_X in light
    if KEY_PLUG in raw:
        plugs = raw[KEY_PLUG]
        info["state"] = bool(plugs[0].get(KEY_STATE, 0)) if plugs else False
    return info


def parse_group(raw: dict) -> dict:
    members_raw = raw.get(KEY_MEMBERS, {})
    member_ids  = (
        members_raw.get("15002", {}).get("9003", [])
        if isinstance(members_raw, dict) else []
    )
    return {
        "id":         raw.get(KEY_ID),
        "name":       raw.get(KEY_NAME),
        "state":      bool(raw.get(KEY_STATE, 0)),
        "brightness": raw.get(KEY_DIMMER),
        "member_ids": member_ids,
    }
