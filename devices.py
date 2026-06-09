"""
Device topology management: reads/writes devices.json and aliases.json.

devices.json is produced by refresh(); aliases.json is maintained manually by the user.
"""
import json
from typing import Optional
from config import DEVICES_FILE, ALIASES_FILE

# ── CoAP key constants ─────────────────────────────────────────────────────

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
KEY_DEV_INFO   = "3"     # ROOT_DEVICE_INFO sub-object
KEY_BATTERY    = "9"     # battery level 0–100 (battery-powered devices only)
KEY_POWER_SRC  = "6"     # power source: 1=mains, 3=battery, …

APP_TYPE = {0: "remote", 2: "light", 3: "plug", 4: "blind", 6: "repeater"}

# CIE XY colour table (scaled to 0–65535)
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

MIRED_MIN = 250   # ~4000K cool white
MIRED_MAX = 454   # ~2200K warm white


# ── devices.json I/O ───────────────────────────────────────────────────────

def load_devices() -> dict:
    """Load devices.json. Returns an empty structure if the file doesn't exist."""
    if not DEVICES_FILE.exists():
        return {"devices": [], "groups": [], "scenes": {}}
    return json.loads(DEVICES_FILE.read_text())


def save_devices(data: dict) -> None:
    DEVICES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


# ── aliases.json I/O ───────────────────────────────────────────────────────

def load_aliases() -> dict:
    """Load aliases.json. Returns an empty dict if the file doesn't exist."""
    if not ALIASES_FILE.exists():
        return {}
    return json.loads(ALIASES_FILE.read_text())


# ── name resolution ────────────────────────────────────────────────────────

def resolve(name: str) -> Optional[dict]:
    """
    Resolve an alias or device name to {"type": "group"|"device", "id": int}.
    Checks aliases.json first, then fuzzy-matches device names in devices.json.
    """
    aliases = load_aliases()

    # exact alias match
    if name in aliases:
        return aliases[name]

    # case-insensitive match
    name_lower = name.lower()
    for key, val in aliases.items():
        if key.lower() == name_lower:
            return val

    # fallback: match against devices.json names
    data = load_devices()
    for g in data.get("groups", []):
        if g.get("name", "").lower() == name_lower:
            return {"type": "group", "id": g["id"]}
    for d in data.get("devices", []):
        if d.get("name", "").lower() == name_lower:
            return {"type": "device", "id": d["id"]}

    return None


# ── scan result parsing ────────────────────────────────────────────────────

def parse_device(raw: dict) -> dict:
    info: dict = {
        "id":        raw.get(KEY_ID),
        "name":      raw.get(KEY_NAME),
        "type":      APP_TYPE.get(raw.get(KEY_TYPE), str(raw.get(KEY_TYPE))),
        "reachable": bool(raw.get(KEY_REACHABLE, 0)),
    }
    dev_info = raw.get(KEY_DEV_INFO, {})
    if KEY_BATTERY in dev_info:
        info["battery"] = dev_info[KEY_BATTERY]
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
