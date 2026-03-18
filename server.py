"""
tradfri-mcp — FastMCP HTTP server
控制 IKEA TRADFRI gateway 下的燈具、插座與場景。

啟動：
    uv run server.py
    MCP_PORT=8765 uv run server.py
"""
import asyncio
import json
import urllib.request
import urllib.parse
from contextlib import asynccontextmanager
from typing import Optional, Literal

from fastmcp import FastMCP

import coap_client as coap
from config import (
    MCP_HOST, MCP_PORT, GATEWAY_IP,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TRADFRI_POLL_INTERVAL,
)
from devices import (
    MIRED_MIN, MIRED_MAX, COLOR_MAP,
    KEY_NAME, KEY_COLOR_TEMP, KEY_COLOR_X, KEY_COLOR_Y,
    load_devices, save_devices, load_aliases, resolve,
    parse_device, parse_group,
)


@asynccontextmanager
async def _lifespan(app):
    tasks = []
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        aliases = load_aliases()
        for name, target in aliases.items():
            if not name.startswith("_"):
                tasks.append(asyncio.create_task(_observe_alias(name, target)))
    yield
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await coap.shutdown()


mcp = FastMCP("tradfri", lifespan=_lifespan)


# ═══════════════════════════════════════════════════════════════════
# Telegram 推播
# ═══════════════════════════════════════════════════════════════════

def _tg_send_sync(token: str, chat_id: str, text: str) -> None:
    url     = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req     = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=10):
        pass


async def _tg_notify(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        await asyncio.to_thread(_tg_send_sync, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, message)
    except Exception:
        pass


# debounce：2 秒內的通知合批成一條訊息
_DEBOUNCE = 2.0
_pending: list[tuple[str, bool]] = []
_flush_task: Optional[asyncio.Task] = None


async def _flush() -> None:
    await asyncio.sleep(_DEBOUNCE)
    global _pending, _flush_task
    batch, _pending, _flush_task = _pending, [], None
    if not batch:
        return
    if len(batch) == 1:
        name, state = batch[0]
        await _tg_notify(f"🏠 {name} {'開燈 💡' if state else '關燈'}")
    else:
        on_  = [n for n, s in batch if s]
        off_ = [n for n, s in batch if not s]
        lines = []
        if on_:  lines.append("開燈 💡 " + "、".join(on_))
        if off_: lines.append("關燈 "    + "、".join(off_))
        await _tg_notify("🏠 " + "\n".join(lines))


def _queue(name: str, state: bool) -> None:
    global _flush_task
    _pending.append((name, state))
    if _flush_task is None or _flush_task.done():
        _flush_task = asyncio.create_task(_flush())


# ═══════════════════════════════════════════════════════════════════
# CoAP OBSERVE：gateway push 狀態變化 → Telegram
# ═══════════════════════════════════════════════════════════════════

def _obs_path_extractor(target: dict):
    """回傳 (coap_path, state_extractor)，無法對應則回傳 (None, None)。"""
    t = target.get("type")
    if t == "group":
        return f"/15004/{target['id']}", lambda raw: bool(raw.get("5850", 0))
    if t == "device":
        return f"/15001/{target['id']}", lambda raw: bool((raw.get("3311") or [{}])[0].get("5850", 0))
    if t == "virtual":
        groups  = target.get("groups", [])
        devices = target.get("devices", [])
        if groups:
            return f"/15004/{groups[0]}", lambda raw: bool(raw.get("5850", 0))
        if devices:
            return f"/15001/{devices[0]}", lambda raw: bool((raw.get("3311") or [{}])[0].get("5850", 0))
    if t == "device_list":
        ids = target.get("ids", [])
        if ids:
            return f"/15001/{ids[0]}", lambda raw: bool((raw.get("3311") or [{}])[0].get("5850", 0))
    return None, None


async def _observe_alias(name: str, target: dict) -> None:
    """
    對單一 alias 建立 CoAP OBSERVE 訂閱。
    gateway push 狀態變化時推播 Telegram。
    連線中斷時重置 context 並自動重試。
    """
    import aiocoap

    path, extract = _obs_path_extractor(target)
    if path is None:
        return

    uri = f"coaps://{GATEWAY_IP}{path}"
    prev_state: Optional[bool] = None

    while True:
        try:
            ctx = await coap.get_ctx()
            req = aiocoap.Message(code=aiocoap.GET, uri=uri, observe=0)
            pr  = ctx.request(req)

            initial = await asyncio.wait_for(pr.response, timeout=30)
            raw = json.loads(initial.payload)
            prev_state = extract(raw)

            async for response in pr.observation:
                raw   = json.loads(response.payload)
                state = extract(raw)
                if prev_state is not None and state != prev_state:
                    _queue(name, state)
                prev_state = state

        except asyncio.CancelledError:
            raise
        except Exception:
            coap.reset_ctx()
            await asyncio.sleep(TRADFRI_POLL_INTERVAL or 30)


# ═══════════════════════════════════════════════════════════════════
# 控制：群組
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def control_group(
    group_id: int,
    state: Optional[bool] = None,
    brightness: Optional[int] = None,
) -> str:
    """
    控制整個群組（開關、亮度）。

    Args:
        group_id:   群組 ID（可從 list_devices 取得）
        state:      true=開，false=關
        brightness: 亮度 0–254
    """
    payload: dict = {}
    if state is not None:
        payload["5850"] = int(state)
    if brightness is not None:
        payload["5851"] = max(0, min(254, brightness))
    if not payload:
        return "未指定任何操作（state 或 brightness 至少提供一個）"
    await coap.coap_put(f"/15004/{group_id}", payload)
    parts = []
    if state is not None:      parts.append("開" if state else "關")
    if brightness is not None: parts.append(f"亮度={brightness}")
    return f"群組 {group_id}：{', '.join(parts)} ✓"


# ═══════════════════════════════════════════════════════════════════
# 控制：單一設備
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def control_device(
    device_id: int,
    state: Optional[bool] = None,
    brightness: Optional[int] = None,
) -> str:
    """
    控制單一設備（燈或插座）。

    Args:
        device_id:  設備 ID（可從 list_devices 取得）
        state:      true=開，false=關
        brightness: 亮度 0–254（僅燈具有效）
    """
    light_payload: dict = {}
    if state is not None:
        light_payload["5850"] = int(state)
    if brightness is not None:
        light_payload["5851"] = max(0, min(254, brightness))
    if not light_payload:
        return "未指定任何操作"
    await coap.coap_put(f"/15001/{device_id}", {"3311": [light_payload]})
    parts = []
    if state is not None:      parts.append("開" if state else "關")
    if brightness is not None: parts.append(f"亮度={brightness}")
    return f"設備 {device_id}：{', '.join(parts)} ✓"


# ═══════════════════════════════════════════════════════════════════
# 控制：依名稱（virtual / group / device / device_list）
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def control_by_name(
    name: str,
    state: Optional[bool] = None,
    brightness: Optional[int] = None,
) -> str:
    """
    依名稱控制設備、群組或虛擬房間。最常用的控制工具。

    Args:
        name:       中文名稱或 alias（如「客廳」、「沙發燈」、「玄關光條」）
        state:      true=開，false=關
        brightness: 亮度 0–254

    Examples:
        control_by_name(name="客廳", state=False)
        control_by_name(name="沙發燈", brightness=100)
        control_by_name(name="玄關", state=True)
    """
    target = resolve(name)
    if target is None:
        return f"找不到「{name}」，請用 list_aliases 確認名稱"

    payload: dict = {}
    if state is not None:
        payload["5850"] = int(state)
    if brightness is not None:
        payload["5851"] = max(0, min(254, brightness))
    if not payload:
        return "未指定任何操作（state 或 brightness 至少提供一個）"

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
        return f"不支援的 alias 類型：{t}"

    action = []
    if state is not None:      action.append("開" if state else "關")
    if brightness is not None: action.append(f"亮度={brightness}")
    return f"「{name}」{'、'.join(action)}：{count} 個目標 ✓"


# ═══════════════════════════════════════════════════════════════════
# 色溫調整
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def set_color_temp(
    name: str,
    direction: Optional[Literal["warm", "cool"]] = None,
    mireds: Optional[int] = None,
    step: int = 50,
) -> str:
    """
    調整白光燈的色溫。支援 alias 名稱。
    Mireds 越大越暖（2200K），越小越冷（4000K）。

    Args:
        name:      alias 名稱（如「客廳」、「沙發燈」）
        direction: "warm"=調暖（+step Mireds），"cool"=調冷（-step Mireds）
        mireds:    直接設定 Mireds（250–454），與 direction 擇一
        step:      相對調整幅度（預設 50 Mireds）

    Examples:
        set_color_temp(name="客廳", direction="warm")
        set_color_temp(name="沙發燈", mireds=370)
        set_color_temp(name="餐桌燈", direction="cool", step=100)
    """
    if mireds is None and direction is None:
        return "請指定 mireds 或 direction"

    target = resolve(name)
    if target is None:
        return f"找不到「{name}」，請用 list_aliases 確認名稱"

    if mireds is not None:
        target_mireds = max(MIRED_MIN, min(MIRED_MAX, mireds))
    else:
        current = 370  # 預設暖白
        try:
            path, _ = _obs_path_extractor(target)
            if path:
                raw = await coap.coap_get(path)
                if path.startswith("/15004"):
                    current = raw.get(KEY_COLOR_TEMP, 370)
                else:
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
        return f"不支援的 alias 類型：{t}"

    kelvin = round(1_000_000 / target_mireds)
    feel   = "暖" if target_mireds > 370 else ("冷" if target_mireds < 310 else "中性")
    return f"「{name}」色溫：{target_mireds} Mireds（≈{kelvin}K，{feel}白），{count} 個目標 ✓"


# ═══════════════════════════════════════════════════════════════════
# 顏色設定
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def set_color(
    name: str,
    color: Literal["red", "green", "blue", "orange", "yellow",
                   "warm_white", "cool_white", "purple", "pink"],
) -> str:
    """
    設定彩色燈的顏色（僅 RGB 燈泡有效）。支援 alias 名稱。

    Args:
        name:  alias 名稱（如「客廳」、「沙發燈」）
        color: red/green/blue/orange/yellow/warm_white/cool_white/purple/pink
    """
    target = resolve(name)
    if target is None:
        return f"找不到「{name}」，請用 list_aliases 確認名稱"

    if color not in COLOR_MAP:
        return f"不支援的顏色：{color}。支援：{', '.join(COLOR_MAP)}"

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
        return f"不支援的 alias 類型：{t}"

    return f"「{name}」顏色設為 {color}，{count} 個目標 ✓"


# ═══════════════════════════════════════════════════════════════════
# 場景
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def activate_scene(group_id: int, scene_id: int) -> str:
    """
    觸發場景（一次套用整個群組的燈光設定）。

    Args:
        group_id: 群組 ID
        scene_id: 場景 ID（可從 list_devices 取得）
    """
    await coap.coap_put(f"/15004/{group_id}", {"9039": scene_id})
    return f"群組 {group_id} 場景 {scene_id} 已觸發 ✓"


# ═══════════════════════════════════════════════════════════════════
# 查詢
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def get_status(
    name: Optional[str] = None,
    device_id: Optional[int] = None,
    group_id: Optional[int] = None,
) -> str:
    """
    查詢設備或群組的即時狀態。優先使用 name（alias 名稱）。

    Args:
        name:      alias 名稱（如「客廳」、「沙發燈」）
        device_id: 設備 ID
        group_id:  群組 ID
    """
    if name is not None:
        target = resolve(name)
        if target is None:
            return f"找不到「{name}」，請用 list_aliases 確認名稱"
        t = target.get("type")
        if t == "device":
            raw = await coap.coap_get(f"/15001/{target['id']}")
            return json.dumps(parse_device(raw), ensure_ascii=False, indent=2)
        elif t == "group":
            raw = await coap.coap_get(f"/15004/{target['id']}")
            return json.dumps(parse_group(raw), ensure_ascii=False, indent=2)
        elif t in ("virtual", "device_list"):
            results = []
            for gid in target.get("groups", []):
                raw = await coap.coap_get(f"/15004/{gid}")
                results.append(parse_group(raw))
            for did in target.get("devices", target.get("ids", [])):
                raw = await coap.coap_get(f"/15001/{did}")
                results.append(parse_device(raw))
            return json.dumps(results, ensure_ascii=False, indent=2)
        else:
            return f"不支援的 alias 類型：{t}"
    elif device_id is not None:
        raw = await coap.coap_get(f"/15001/{device_id}")
        return json.dumps(parse_device(raw), ensure_ascii=False, indent=2)
    elif group_id is not None:
        raw = await coap.coap_get(f"/15004/{group_id}")
        return json.dumps(parse_group(raw), ensure_ascii=False, indent=2)
    else:
        return "請指定 name、device_id 或 group_id"


@mcp.tool()
async def list_devices() -> str:
    """
    列出所有設備、群組與場景（含 alias 對應）。
    資料來自 devices.json（快取），如需更新請呼叫 refresh_devices。
    """
    data    = load_devices()
    aliases = load_aliases()

    alias_lookup: dict = {"group": {}, "device": {}}
    for alias_name, target in aliases.items():
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
    列出所有 alias 名稱與類型（輕量，適合控制前確認名稱）。

    類型說明：
        virtual     → 虛擬房間（包含多個 groups + devices）
        group       → IKEA 群組
        device      → 單一設備
        device_list → 多個設備的集合
    """
    aliases = load_aliases()
    summary = {
        name: target.get("type", "unknown")
        for name, target in aliases.items()
        if not name.startswith("_")
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


@mcp.tool()
async def refresh_devices() -> str:
    """
    重新掃描 gateway，更新 devices.json。
    若拓撲有變動（新增/移除設備或群組），回傳 diff。
    """
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

    lines = [f"掃描完成：{len(devices)} 設備，{len(groups)} 群組"]
    if new_dev - old_dev: lines.append(f"  + 新設備: {sorted(new_dev - old_dev)}")
    if old_dev - new_dev: lines.append(f"  - 移除設備: {sorted(old_dev - new_dev)}")
    if new_grp - old_grp: lines.append(f"  + 新群組: {sorted(new_grp - old_grp)}")
    if old_grp - new_grp: lines.append(f"  - 移除群組: {sorted(old_grp - new_grp)}")
    if not any([new_dev - old_dev, old_dev - new_dev, new_grp - old_grp, old_grp - new_grp]):
        lines.append("  （無拓撲變動）")
    return "\n".join(lines)


@mcp.tool()
async def find_by_name(name: str) -> str:
    """
    根據名稱查找對應的設備/群組 ID。

    Args:
        name: 中文名稱、alias 或 gateway 原始名稱
    """
    result = resolve(name)
    if result is None:
        data = load_devices()
        all_names = (
            [g.get("name", "") for g in data.get("groups", [])] +
            [d.get("name", "") for d in data.get("devices", [])] +
            list(load_aliases().keys())
        )
        return f"找不到「{name}」。已知名稱：{', '.join(filter(None, all_names))}"
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def send_notification(message: str) -> str:
    """
    推播訊息到 Telegram（需設定 TELEGRAM_BOT_TOKEN 與 TELEGRAM_CHAT_ID）。
    未設定時靜默略過。

    Args:
        message: 要傳送的文字訊息
    """
    await _tg_notify(message)
    return "已發送" if (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID) else "未設定 Telegram，略過通知"


# ═══════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host=MCP_HOST, port=MCP_PORT)
