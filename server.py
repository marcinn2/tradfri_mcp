"""
tradfri-mcp — FastMCP HTTP server
Controls lights, sockets, and scenes on an IKEA TRADFRI gateway.

Start:
    uv run server.py
    MCP_PORT=8765 uv run server.py
"""
import json
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from pydantic import Field

# digits-only string field — renders as a numeric text input, empty = not provided
_IntStr = Annotated[str, Field(default="", pattern=r"^\d*$")]

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier

# tool call logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
_log = logging.getLogger("mcp-tool")

def _safe(name: str) -> str:
    return name[:64].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

import coap_client as coap
from config import MCP_HOST, MCP_PORT, MCP_AUTH_TOKEN, MCP_ALLOW_INSECURE
from devices import (
    MIRED_MIN, MIRED_MAX, COLOR_MAP,
    KEY_NAME, KEY_COLOR_TEMP, KEY_COLOR_X, KEY_COLOR_Y,
    load_devices, save_devices, load_aliases, resolve,
    parse_device, parse_group,
)


@asynccontextmanager
async def _lifespan(app):
    yield
    await coap.shutdown()


_auth = (
    StaticTokenVerifier(tokens={MCP_AUTH_TOKEN: {"client_id": "tradfri", "scopes": []}})
    if MCP_AUTH_TOKEN else None
)
mcp = FastMCP("tradfri", lifespan=_lifespan, auth=_auth)


# ═══════════════════════════════════════════════════════════════════
# control: group
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def control_group(
    group_id: int,
    state: Literal["on", "off", ""] = "",
    brightness: _IntStr = "",
) -> str:
    """
    Control an entire group (on/off, brightness).

    Args:
        group_id:   group ID (from list_devices)
        state:      "on" or "off" (leave empty to skip)
        brightness: 0–254 (leave empty to skip)
    """
    bval = int(brightness) if brightness else None
    payload: dict = {}
    if state == "on":
        payload["5850"] = 1
    elif state == "off":
        payload["5850"] = 0
    if bval is not None:
        payload["5851"] = max(0, min(254, bval))
    if not payload:
        return "No operation specified (provide state or brightness)"
    _log.info("control_group(group_id=%s, state=%s, brightness=%s)", group_id, state, bval)
    await coap.coap_put(f"/15004/{group_id}", payload)
    parts = []
    if state:            parts.append(state)
    if bval is not None: parts.append(f"brightness={bval}")
    return f"group {group_id}: {', '.join(parts)} ✓"


# ═══════════════════════════════════════════════════════════════════
# control: single device
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def control_device(
    device_id: int,
    state: Literal["on", "off", ""] = "",
    brightness: _IntStr = "",
) -> str:
    """
    Control a single device (light or socket).

    Args:
        device_id:  device ID (from list_devices)
        state:      "on" or "off" (leave empty to skip)
        brightness: 0–254 (leave empty to skip, lights only)
    """
    bval = int(brightness) if brightness else None
    light_payload: dict = {}
    if state == "on":
        light_payload["5850"] = 1
    elif state == "off":
        light_payload["5850"] = 0
    if bval is not None:
        light_payload["5851"] = max(0, min(254, bval))
    if not light_payload:
        return "No operation specified"
    _log.info("control_device(device_id=%s, state=%s, brightness=%s)", device_id, state, bval)
    await coap.coap_put(f"/15001/{device_id}", {"3311": [light_payload]})
    parts = []
    if state:            parts.append(state)
    if bval is not None: parts.append(f"brightness={bval}")
    return f"device {device_id}: {', '.join(parts)} ✓"


# ═══════════════════════════════════════════════════════════════════
# control: by name (virtual / group / device / device_list)
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def control_by_name(
    name: str,
    state: Literal["on", "off", ""] = "",
    brightness: _IntStr = "",
) -> str:
    """
    Control a device, group, or virtual room by name. The most-used control tool.

    Args:
        name:       alias or device name
        state:      "on" or "off" (leave empty to skip)
        brightness: 0–254 (leave empty to skip)
    """
    bval = int(brightness) if brightness else None
    _log.info("control_by_name(name=%r, state=%s, brightness=%s)", name, state, bval)
    target = resolve(name)
    if target is None:
        return f"'{_safe(name)}' not found — use list_aliases to check available names"

    payload: dict = {}
    if state == "on":
        payload["5850"] = 1
    elif state == "off":
        payload["5850"] = 0
    if bval is not None:
        payload["5851"] = max(0, min(254, bval))
    if not payload:
        return "No operation specified (provide state or brightness)"

    t = target.get("type")
    count = 0

    if t == "group":
        await coap.coap_put(f"/15004/{target['id']}", payload)
        count = 1
    elif t == "device":
        await coap.coap_put(f"/15001/{target['id']}", {"3311": [payload]})
        count = 1
    elif t == "device_list":
        for did in target.get("ids", []):
            await coap.coap_put(f"/15001/{did}", {"3311": [payload]})
            count += 1
    elif t == "virtual":
        for gid in target.get("groups", []):
            await coap.coap_put(f"/15004/{gid}", payload)
            count += 1
        for did in target.get("devices", []):
            await coap.coap_put(f"/15001/{did}", {"3311": [payload]})
            count += 1
    else:
        return f"unsupported alias type: {t}"

    action = []
    if state:            action.append(state)
    if bval is not None: action.append(f"brightness={bval}")
    return f"'{_safe(name)}' {', '.join(action)}: {count} target(s) ✓"


# ═══════════════════════════════════════════════════════════════════
# colour temperature
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def set_color_temp(
    name: str,
    direction: Literal["warm", "cool", ""] = "",
    mireds: _IntStr = "",
    step: int = 50,
) -> str:
    """
    Adjust white-light colour temperature. Accepts alias names.
    Higher mireds = warmer (2200K); lower mireds = cooler (4000K).

    Args:
        name:      alias name
        direction: "warm" or "cool" (relative step); leave empty when using mireds
        mireds:    absolute value 250–454 (leave empty to use direction instead)
        step:      relative adjustment when using direction (default 50 mireds)
    """
    mval = int(mireds) if mireds else None
    _log.info("set_color_temp(name=%r, direction=%s, mireds=%s, step=%s)", name, direction, mval, step)
    if not mval and not direction:
        return "Specify mireds or direction"

    target = resolve(name)
    if target is None:
        return f"'{_safe(name)}' not found — use list_aliases to check available names"

    if mval:
        target_mireds = max(MIRED_MIN, min(MIRED_MAX, mval))
    else:
        current = 370  # neutral default
        try:
            t = target.get("type")
            if t == "group":
                raw = await coap.coap_get(f"/15004/{target['id']}")
                current = raw.get(KEY_COLOR_TEMP, 370)
            elif t in ("device", "device_list", "virtual"):
                ids = (
                    [target["id"]] if t == "device" else
                    target.get("ids", []) if t == "device_list" else
                    target.get("devices", [])
                )
                if ids:
                    raw = await coap.coap_get(f"/15001/{ids[0]}")
                    lights = raw.get("3311", [{}])
                    current = lights[0].get(KEY_COLOR_TEMP, 370) if lights else 370
        except Exception:
            pass
        delta = step if direction == "warm" else -step
        target_mireds = max(MIRED_MIN, min(MIRED_MAX, current + delta))

    t = target.get("type")
    count = 0
    if t == "group":
        await coap.coap_put(f"/15004/{target['id']}", {KEY_COLOR_TEMP: target_mireds})
        count = 1
    elif t == "device":
        await coap.coap_put(f"/15001/{target['id']}", {"3311": [{KEY_COLOR_TEMP: target_mireds}]})
        count = 1
    elif t == "device_list":
        for did in target.get("ids", []):
            await coap.coap_put(f"/15001/{did}", {"3311": [{KEY_COLOR_TEMP: target_mireds}]})
            count += 1
    elif t == "virtual":
        for gid in target.get("groups", []):
            await coap.coap_put(f"/15004/{gid}", {KEY_COLOR_TEMP: target_mireds})
            count += 1
        for did in target.get("devices", []):
            await coap.coap_put(f"/15001/{did}", {"3311": [{KEY_COLOR_TEMP: target_mireds}]})
            count += 1
    else:
        return f"unsupported alias type: {t}"

    kelvin = round(1_000_000 / target_mireds)
    feel   = "warm" if target_mireds > 370 else ("cool" if target_mireds < 310 else "neutral")
    return f"'{_safe(name)}' colour temp: {target_mireds} Mireds (≈{kelvin}K, {feel}), {count} target(s) ✓"


# ═══════════════════════════════════════════════════════════════════
# colour
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def set_color(
    name: str,
    color: Literal["red", "green", "blue", "orange", "yellow",
                   "warm_white", "cool_white", "purple", "pink"],
) -> str:
    """
    Set the colour of RGB bulbs. Accepts alias names.

    Args:
        name:  alias name
        color: red/green/blue/orange/yellow/warm_white/cool_white/purple/pink
    """
    _log.info("set_color(name=%r, color=%s)", name, color)
    target = resolve(name)
    if target is None:
        return f"'{_safe(name)}' not found — use list_aliases to check available names"

    if color not in COLOR_MAP:
        return f"unsupported colour: {color}. Supported: {', '.join(COLOR_MAP)}"

    x, y = COLOR_MAP[color]
    cp = {KEY_COLOR_X: x, KEY_COLOR_Y: y}
    t = target.get("type")
    count = 0

    if t == "device":
        await coap.coap_put(f"/15001/{target['id']}", {"3311": [cp]})
        count = 1
    elif t == "device_list":
        for did in target.get("ids", []):
            await coap.coap_put(f"/15001/{did}", {"3311": [cp]})
            count += 1
    elif t == "virtual":
        for did in target.get("devices", []):
            await coap.coap_put(f"/15001/{did}", {"3311": [cp]})
            count += 1
    elif t == "group":
        await coap.coap_put(f"/15004/{target['id']}", cp)
        count = 1
    else:
        return f"unsupported alias type: {t}"

    return f"'{_safe(name)}' colour set to {color}, {count} target(s) ✓"


# ═══════════════════════════════════════════════════════════════════
# scenes
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def activate_scene(group_id: int, scene_id: int) -> str:
    """
    Activate a scene (applies a full group lighting preset in one shot).

    Args:
        group_id: group ID
        scene_id: scene ID (from list_devices)
    """
    _log.info("activate_scene(group_id=%s, scene_id=%s)", group_id, scene_id)
    await coap.coap_put(f"/15004/{group_id}", {"9039": scene_id})
    return f"group {group_id} scene {scene_id} activated ✓"


# ═══════════════════════════════════════════════════════════════════
# query
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def get_status(
    name: str = "",
    device_id: _IntStr = "",
    group_id: _IntStr = "",
) -> str:
    """
    Get the current state of a device or group. Prefer name (alias).
    Provide exactly one of: name, device_id, or group_id.

    Args:
        name:      alias name (e.g. "Living Room")
        device_id: device ID from list_devices (e.g. 65553) — leave empty if using name
        group_id:  group ID from list_devices (e.g. 131079) — leave empty if using name
    """
    did = int(device_id.strip()) if device_id.strip() else None
    gid = int(group_id.strip()) if group_id.strip() else None
    _log.info("get_status(name=%r, device_id=%s, group_id=%s)", name, did, gid)
    if name:
        target = resolve(name)
        if target is None:
            return f"'{_safe(name)}' not found — use list_aliases to check available names"
        t = target.get("type")
        if t == "device":
            raw = await coap.coap_get(f"/15001/{target['id']}")
            return json.dumps(parse_device(raw), ensure_ascii=False, indent=2)
        elif t == "group":
            raw = await coap.coap_get(f"/15004/{target['id']}")
            return json.dumps(parse_group(raw), ensure_ascii=False, indent=2)
        elif t in ("virtual", "device_list"):
            results = []
            for g in target.get("groups", []):
                raw = await coap.coap_get(f"/15004/{g}")
                results.append(parse_group(raw))
            for d in target.get("devices", target.get("ids", [])):
                raw = await coap.coap_get(f"/15001/{d}")
                results.append(parse_device(raw))
            return json.dumps(results, ensure_ascii=False, indent=2)
        else:
            return f"unsupported alias type: {t}"
    elif did:
        raw = await coap.coap_get(f"/15001/{did}")
        return json.dumps(parse_device(raw), ensure_ascii=False, indent=2)
    elif gid:
        raw = await coap.coap_get(f"/15004/{gid}")
        return json.dumps(parse_group(raw), ensure_ascii=False, indent=2)
    else:
        return "Specify name, device_id, or group_id"


@mcp.tool()
async def list_devices() -> str:
    """
    List all devices, groups, and scenes (with alias mappings).
    Data is from devices.json (cached); call refresh_devices to update.
    """
    _log.info("list_devices()")
    data    = load_devices()
    aliases = load_aliases()

    alias_lookup: dict = {"group": {}, "device": {}}
    for alias_name, target in aliases.items():
        if not isinstance(target, dict):
            continue
        t = target.get("type")
        i = target.get("id")
        if t in alias_lookup and i is not None:
            alias_lookup[t].setdefault(i, []).append(alias_name)

    result = {
        "groups":  [],
        "devices": [],
        "scenes":  data.get("scenes", {}),
        "aliases": aliases,
    }
    for g in data.get("groups", []):
        entry = dict(g)
        entry["aliases"] = alias_lookup["group"].get(g["id"], [])
        result["groups"].append(entry)
    for d in data.get("devices", []):
        entry = dict(d)
        entry["aliases"] = alias_lookup["device"].get(d["id"], [])
        result["devices"].append(entry)

    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
async def list_aliases() -> str:
    """
    List all alias names and types (lightweight, useful before controlling by name).

    Types:
        virtual     → virtual room (contains multiple groups + devices)
        group       → IKEA group
        device      → single device
        device_list → collection of multiple devices
    """
    _log.info("list_aliases()")
    aliases = load_aliases()
    summary = {
        name: target.get("type", "unknown")
        for name, target in aliases.items()
        if not name.startswith("_")
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


@mcp.tool()
async def battery_report(threshold: int = 100, live: bool = False) -> str:
    """
    Report battery levels of all battery-powered devices (remotes, sensors, blinds),
    sorted lowest first. Useful for spotting devices that need new batteries.

    Args:
        threshold: only include devices at or below this percentage (default 100 = all)
        live:      query the gateway for fresh values; otherwise read cached devices.json
    """
    _log.info("battery_report(threshold=%s, live=%s)", threshold, live)

    if live:
        device_ids = await coap.coap_get("/15001")
        devices = []
        for did in device_ids:
            raw = await coap.coap_get(f"/15001/{did}")
            devices.append(parse_device(raw))
    else:
        devices = load_devices().get("devices", [])

    batt = [
        {"id": d["id"], "name": d.get("name"), "type": d.get("type"), "battery": d["battery"]}
        for d in devices
        if d.get("battery") is not None and d["battery"] <= threshold
    ]
    batt.sort(key=lambda d: d["battery"])

    if not batt:
        scope = f" at or below {threshold}%" if threshold < 100 else ""
        hint = "" if live else " (cached — pass live=true to re-query the gateway)"
        return f"No battery-powered devices found{scope}.{hint}"

    return json.dumps(batt, ensure_ascii=False, indent=2)


@mcp.tool()
async def refresh_devices() -> str:
    """
    Re-scan the gateway and update devices.json.
    Returns a diff if the topology has changed (devices/groups added or removed).
    """
    _log.info("refresh_devices()")
    old_data = load_devices()

    device_ids = await coap.coap_get("/15001")
    devices = []
    for did in device_ids:
        raw = await coap.coap_get(f"/15001/{did}")
        devices.append(parse_device(raw))

    group_ids = await coap.coap_get("/15004")
    groups = []
    scenes: dict = {}
    for gid in group_ids:
        raw = await coap.coap_get(f"/15004/{gid}")
        groups.append(parse_group(raw))
        try:
            scene_ids = await coap.coap_get(f"/15005/{gid}")
            scene_list = []
            for sid in scene_ids:
                s = await coap.coap_get(f"/15005/{gid}/{sid}")
                scene_list.append({"id": sid, "name": s.get(KEY_NAME, "?")})
            scenes[str(gid)] = scene_list
        except Exception:
            scenes[str(gid)] = []

    new_data = {"devices": devices, "groups": groups, "scenes": scenes}
    save_devices(new_data)

    old_dev = {d["id"] for d in old_data.get("devices", [])}
    new_dev = {d["id"] for d in devices}
    old_grp = {g["id"] for g in old_data.get("groups", [])}
    new_grp = {g["id"] for g in groups}

    lines = [f"scan complete: {len(devices)} device(s), {len(groups)} group(s)"]
    if new_dev - old_dev: lines.append(f"  + added devices: {sorted(new_dev - old_dev)}")
    if old_dev - new_dev: lines.append(f"  - removed devices: {sorted(old_dev - new_dev)}")
    if new_grp - old_grp: lines.append(f"  + added groups: {sorted(new_grp - old_grp)}")
    if old_grp - new_grp: lines.append(f"  - removed groups: {sorted(old_grp - new_grp)}")
    if not any([new_dev - old_dev, old_dev - new_dev, new_grp - old_grp, old_grp - new_grp]):
        lines.append("  (no topology changes)")
    return "\n".join(lines)


@mcp.tool()
async def find_by_name(name: str) -> str:
    """
    Look up the device/group ID for a given name.

    Args:
        name: alias or gateway device name
    """
    _log.info("find_by_name(name=%r)", name)
    result = resolve(name)
    if result is None:
        data = load_devices()
        all_names = (
            [g.get("name", "") for g in data.get("groups", [])] +
            [d.get("name", "") for d in data.get("devices", [])] +
            list(load_aliases().keys())
        )
        return f"'{_safe(name)}' not found. Known names: {', '.join(filter(None, all_names))}"
    return json.dumps(result, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════
# prompts — reusable templates the MCP client can surface to the user.
# Each returns instructions that drive the control tools above; they don't
# call CoAP directly, so the assistant stays in charge of confirmation.
# ═══════════════════════════════════════════════════════════════════

@mcp.prompt
def movie_night(room: str = "Living Room") -> str:
    """Dim a room to a warm, low-light level for watching a film."""
    return (
        f"Set up '{room}' for movie night: use control_by_name to turn it on at a low "
        f"brightness (around 40 of 254), then set_color_temp with direction=warm. "
        f"Confirm what you changed in one short line."
    )


@mcp.prompt
def good_morning(room: str = "Bedroom") -> str:
    """Bright, cool light to wake up to."""
    return (
        f"Good morning routine for '{room}': use control_by_name to turn it on at full "
        f"brightness (254), then set_color_temp with mireds=250 for a cool, energizing "
        f"white. Keep the confirmation to one line."
    )


@mcp.prompt
def good_night(keep_on: str = "") -> str:
    """Turn everything off for bed, optionally leaving one room on."""
    base = (
        "Bedtime: call list_aliases to see the rooms, then use control_by_name with "
        "state=off to turn each one off."
    )
    if keep_on.strip():
        base += (
            f" Leave '{keep_on.strip()}' on but dim it (brightness around 30 of 254, "
            f"set_color_temp direction=warm)."
        )
    return base + " Summarize what you turned off in one line."


@mcp.prompt
def set_mood(room: str, mood: str) -> str:
    """Adjust a room to match a mood (e.g. cozy, focus, party, relax)."""
    return (
        f"Set '{room}' to a '{mood}' mood. Decide sensible values and apply them with "
        f"control_by_name (on/brightness), set_color_temp (warm/cool), and set_color for "
        f"RGB bulbs if a colour suits the mood. Guidance: cozy/relax = low brightness + "
        f"warm; focus/work = high brightness + cool; party = mid brightness + a vivid "
        f"colour. State the brightness/temp/colour you chose in one line."
    )


@mcp.prompt
def battery_check() -> str:
    """Report which battery devices are running low and may need replacing."""
    return (
        "Call battery_report to list battery-powered devices (remotes, sensors, blinds). "
        "Highlight anything at or below 20% as needing a new battery soon, and note if "
        "the data is cached (suggest live=true for fresh values if anything looks off)."
    )


# ═══════════════════════════════════════════════════════════════════
# entry point
# ═══════════════════════════════════════════════════════════════════

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _security_preflight() -> None:
    """
    Refuse to start when the server is reachable beyond loopback without a bearer token.
    Binding to 0.0.0.0 (the Docker default) plus no MCP_AUTH_TOKEN means anyone on the
    network can read device names/topology and control the home. Operators who really
    want that on a trusted LAN can opt out with MCP_ALLOW_INSECURE=1.
    Raises SystemExit on an insecure configuration.
    """
    exposed = MCP_HOST not in _LOOPBACK_HOSTS
    if exposed and not MCP_AUTH_TOKEN:
        if MCP_ALLOW_INSECURE:
            _log.warning("=" * 64)
            _log.warning("SECURITY: bound to %s:%s with NO authentication (MCP_ALLOW_INSECURE).", MCP_HOST, MCP_PORT)
            _log.warning("Anyone on the network can control your home and read device names.")
            _log.warning("=" * 64)
        else:
            _log.error("=" * 64)
            _log.error("REFUSING TO START: bound to %s:%s with NO authentication.", MCP_HOST, MCP_PORT)
            _log.error("Anyone on the network could control your home and read device names.")
            _log.error("Fix one of the following, then restart:")
            _log.error("  • set MCP_AUTH_TOKEN to require a bearer token (recommended), or")
            _log.error("  • set MCP_HOST=127.0.0.1 if the MCP client runs on this same host, or")
            _log.error("  • set MCP_ALLOW_INSECURE=1 to override (trusted LAN only).")
            _log.error("=" * 64)
            raise SystemExit(1)
    elif exposed:
        _log.info("Bound to %s:%s with bearer-token authentication enabled.", MCP_HOST, MCP_PORT)


if __name__ == "__main__":
    _security_preflight()
    mcp.run(transport="streamable-http", host=MCP_HOST, port=MCP_PORT)
