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
    KEY_ID, KEY_NAME, KEY_STATE, KEY_DIMMER,
    KEY_COLOR_TEMP, KEY_COLOR_X, KEY_COLOR_Y,
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


mcp = FastMCP("tradfri", lifespan=_lifespan)


# ═══════════════════════════════════════════════════════════════════
# Telegram 推播（內部 helper，設定缺失時靜默略過）
# ═══════════════════════════════════════════════════════════════════

def _tg_send_sync(token: str, chat_id: str, text: str) -> None:
    """同步送出 Telegram sendMessage（在 thread 裡執行）。"""
    url     = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req     = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=10):
        pass


async def tg_notify(message: str) -> bool:
    """
    推播訊息到 Telegram。
    若 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 未設定，靜默回傳 False。
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        await asyncio.to_thread(_tg_send_sync, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, message)
        return True
    except Exception:
        return False


# debounce：2 秒內的通知合批成一條訊息
_DEBOUNCE_SECS = 2.0
_pending_notifications: list[tuple[str, bool]] = []   # (alias名稱, 新狀態)
_flush_task: Optional[asyncio.Task] = None


async def _flush_notifications() -> None:
    await asyncio.sleep(_DEBOUNCE_SECS)
    global _pending_notifications, _flush_task
    batch, _pending_notifications, _flush_task = _pending_notifications, [], None
    if not batch:
        return
    if len(batch) == 1:
        name, state = batch[0]
        await tg_notify(f"🏠 {name} {'開燈 💡' if state else '關燈'}")
    else:
        on_names  = [n for n, s in batch if s]
        off_names = [n for n, s in batch if not s]
        lines = []
        if on_names:  lines.append("開燈 💡 " + "、".join(on_names))
        if off_names: lines.append("關燈 "    + "、".join(off_names))
        await tg_notify("🏠 " + "\n".join(lines))


def _queue_notification(name: str, state: bool) -> None:
    """把狀態變化加入 pending，第一筆觸發 debounce timer。"""
    global _flush_task
    _pending_notifications.append((name, state))
    if _flush_task is None or _flush_task.done():
        _flush_task = asyncio.create_task(_flush_notifications())


# ═══════════════════════════════════════════════════════════════════
# CoAP OBSERVE：gateway 主動 push 狀態變化 → 直接推播 Telegram
# ═══════════════════════════════════════════════════════════════════

def _observe_path_and_extractor(target: dict):
    """
    回傳 (coap_path, state_extractor)。
    virtual / device_list 以第一個 group / device 為代表節點。
    無法對應則回傳 (None, None)。
    """
    t = target.get("type")
    if t == "group":
        path = f"/15004/{target['id']}"
        extract = lambda raw: bool(raw.get("5850", 0))
    elif t == "device":
        path = f"/15001/{target['id']}"
        extract = lambda raw: bool((raw.get("3311") or [{}])[0].get("5850", 0))
    elif t == "virtual":
        groups = target.get("groups", [])
        devices = target.get("devices", [])
        if groups:
            path = f"/15004/{groups[0]}"
            extract = lambda raw: bool(raw.get("5850", 0))
        elif devices:
            path = f"/15001/{devices[0]}"
            extract = lambda raw: bool((raw.get("3311") or [{}])[0].get("5850", 0))
        else:
            return None, None
    elif t == "device_list":
        ids = target.get("ids", [])
        if not ids:
            return None, None
        path = f"/15001/{ids[0]}"
        extract = lambda raw: bool((raw.get("3311") or [{}])[0].get("5850", 0))
    else:
        return None, None
    return path, extract


async def _observe_alias(name: str, target: dict) -> None:
    """
    對單一 alias 建立 CoAP OBSERVE 訂閱。
    gateway 主動 push 時解析狀態，變化則推播 Telegram。
    訂閱中斷（逾時 / 網路錯誤）時自動重試，不 crash。
    """
    import aiocoap

    path, extract = _observe_path_and_extractor(target)
    if path is None:
        return

    uri = f"coaps://{GATEWAY_IP}{path}"
    prev_state: Optional[bool] = None

    while True:
        try:
            ctx = await coap.get_ctx()
            req = aiocoap.Message(code=aiocoap.GET, uri=uri, observe=0)
            pr  = ctx.request(req)

            # 初始回應：建立基線，不發通知
            initial = await pr.response
            raw = json.loads(initial.payload)
            prev_state = extract(raw)

            # 持續接收 gateway push
            async for response in pr.observation:
                raw   = json.loads(response.payload)
                state = extract(raw)
                if prev_state is not None and state != prev_state:
                    _queue_notification(name, state)
                prev_state = state

        except asyncio.CancelledError:
            raise  # lifespan 關閉，正常退出
        except Exception:
            await asyncio.sleep(TRADFRI_POLL_INTERVAL or 30)  # 重試間隔


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
    控制整個群組（適用於房間等級的操作）。

    Args:
        group_id:   群組 ID（可從 list_devices 取得）
        state:      true=開燈，false=關燈，省略=維持現狀
        brightness: 亮度 0–254，省略=維持現狀

    Examples:
        control_group(group_id=4, state=True, brightness=200)
        control_group(group_id=4, state=False)
        control_group(group_id=4, brightness=80)
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
    if state is not None:
        parts.append("開燈" if state else "關燈")
    if brightness is not None:
        parts.append(f"亮度={brightness}")
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
    if state is not None:
        parts.append("開" if state else "關")
    if brightness is not None:
        parts.append(f"亮度={brightness}")
    return f"設備 {device_id}：{', '.join(parts)} ✓"


# ═══════════════════════════════════════════════════════════════════
# 控制：色溫
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def set_color_temp(
    device_id: int,
    mireds: Optional[int] = None,
    direction: Optional[Literal["warm", "cool"]] = None,
    step: int = 50,
) -> str:
    """
    調整白光燈的色溫。Mireds 越大越暖（2200K），越小越冷（4000K）。

    Args:
        device_id: 設備 ID
        mireds:    直接設定 Mireds 值（250–454）
        direction: "warm"=調暖（+step Mireds），"cool"=調冷（-step Mireds）
        step:      相對調整幅度（預設 50）

    Examples:
        set_color_temp(device_id=65537, direction="warm")
        set_color_temp(device_id=65537, mireds=370)
        set_color_temp(device_id=65537, direction="cool", step=100)
    """
    if mireds is None and direction is None:
        return "請指定 mireds 或 direction"

    target: int
    if mireds is not None:
        target = max(MIRED_MIN, min(MIRED_MAX, mireds))
    else:
        # 需要先查當前值
        try:
            raw = await coap.coap_get(f"/15001/{device_id}")
            lights = raw.get("3311", [{}])
            current = lights[0].get(KEY_COLOR_TEMP, 370) if lights else 370
        except Exception:
            current = 370  # 預設暖白

        delta = step if direction == "warm" else -step
        target = max(MIRED_MIN, min(MIRED_MAX, current + delta))

    await coap.coap_put(f"/15001/{device_id}", {"3311": [{KEY_COLOR_TEMP: target}]})
    kelvin = round(1_000_000 / target)
    feel   = "暖" if target > 370 else ("冷" if target < 310 else "中性")
    return f"設備 {device_id} 色溫：{target} Mireds（≈{kelvin}K，{feel}白）✓"


# ═══════════════════════════════════════════════════════════════════
# 控制：顏色
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def set_color(
    device_id: int,
    color: Literal["red", "green", "blue", "orange", "yellow",
                   "warm_white", "cool_white", "purple", "pink"],
) -> str:
    """
    設定彩色燈的顏色（僅支援 RGB 燈泡）。

    Args:
        device_id: 設備 ID
        color:     顏色名稱。支援：
                   red（紅）, green（綠）, blue（藍）, orange（橙）,
                   yellow（黃）, warm_white（暖白）, cool_white（冷白）,
                   purple（紫）, pink（粉）
    """
    if color not in COLOR_MAP:
        return f"不支援的顏色：{color}。支援：{', '.join(COLOR_MAP)}"

    x, y = COLOR_MAP[color]
    await coap.coap_put(f"/15001/{device_id}", {"3311": [{KEY_COLOR_X: x, KEY_COLOR_Y: y}]})
    return f"設備 {device_id} 顏色設為 {color} ✓"


# ═══════════════════════════════════════════════════════════════════
# 控制：場景
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
    device_id: Optional[int] = None,
    group_id: Optional[int] = None,
) -> str:
    """
    查詢設備或群組的即時狀態（直接向 gateway 查詢）。

    Args:
        device_id: 設備 ID（與 group_id 擇一）
        group_id:  群組 ID（與 device_id 擇一）
    """
    if device_id is not None:
        raw = await coap.coap_get(f"/15001/{device_id}")
        info = parse_device(raw)
        return json.dumps(info, ensure_ascii=False, indent=2)
    elif group_id is not None:
        raw = await coap.coap_get(f"/15004/{group_id}")
        info = parse_group(raw)
        return json.dumps(info, ensure_ascii=False, indent=2)
    else:
        return "請指定 device_id 或 group_id"


@mcp.tool()
async def list_devices() -> str:
    """
    列出所有設備、群組與場景，包含 alias 對應。
    資料來自 devices.json（快取），如需更新請呼叫 refresh_devices。
    """
    data    = load_devices()
    aliases = load_aliases()

    # 為每個 group / device 附上 alias 名稱
    alias_lookup: dict[str, dict[int, list[str]]] = {"group": {}, "device": {}}
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
async def refresh_devices() -> str:
    """
    重新掃描 gateway，更新 devices.json。
    若拓撲有變動（新增/移除設備或群組），回傳 diff；無變動則靜默。
    """
    old_data = load_devices()

    # 掃描設備
    device_ids = await coap.coap_get("/15001")
    devices = []
    for did in device_ids:
        raw = await coap.coap_get(f"/15001/{did}")
        devices.append(parse_device(raw))

    # 掃描群組
    group_ids = await coap.coap_get("/15004")
    groups = []
    scenes: dict = {}
    for gid in group_ids:
        raw = await coap.coap_get(f"/15004/{gid}")
        groups.append(parse_group(raw))
        # 掃描場景
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

    # diff
    old_ids_dev   = {d["id"] for d in old_data.get("devices", [])}
    new_ids_dev   = {d["id"] for d in devices}
    old_ids_grp   = {g["id"] for g in old_data.get("groups", [])}
    new_ids_grp   = {g["id"] for g in groups}

    added_dev   = new_ids_dev - old_ids_dev
    removed_dev = old_ids_dev - new_ids_dev
    added_grp   = new_ids_grp - old_ids_grp
    removed_grp = old_ids_grp - new_ids_grp

    lines = [f"掃描完成：{len(devices)} 設備，{len(groups)} 群組"]
    if added_dev:
        lines.append(f"  + 新設備: {sorted(added_dev)}")
    if removed_dev:
        lines.append(f"  - 移除設備: {sorted(removed_dev)}")
    if added_grp:
        lines.append(f"  + 新群組: {sorted(added_grp)}")
    if removed_grp:
        lines.append(f"  - 移除群組: {sorted(removed_grp)}")
    if not (added_dev or removed_dev or added_grp or removed_grp):
        lines.append("  （無拓撲變動）")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════
# 控制：依名稱（支援虛擬房間）
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def control_by_name(
    name: str,
    state: Optional[bool] = None,
    brightness: Optional[int] = None,
) -> str:
    """
    依名稱或 alias 控制設備、群組或虛擬房間。
    這是最常用的控制 tool — 直接說「客廳」、「沙發燈」、「玄關光條」即可。

    支援 alias 類型：
        group       → 控制單一 IKEA 群組
        device      → 控制單一設備
        device_list → 批次控制多個設備
        virtual     → 虛擬房間，批次控制 groups + devices

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
        return f"找不到「{name}」，請先用 find_by_name 確認名稱"

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

    action_parts = []
    if state is not None:
        action_parts.append("開" if state else "關")
    if brightness is not None:
        action_parts.append(f"亮度={brightness}")

    return f"「{name}」{', '.join(action_parts)}：{count} 個目標 ✓"


# ═══════════════════════════════════════════════════════════════════
# 輔助：alias 清單（輕量）
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def list_aliases() -> str:
    """
    列出所有已設定的 alias 名稱與類型，供 LLM 快速確認可控制的目標。
    比 list_devices 輕量，適合在控制前確認名稱是否存在。

    Returns:
        JSON: {alias名稱: 類型}，例如 {"客廳": "virtual", "沙發燈": "group"}

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


# ═══════════════════════════════════════════════════════════════════
# 輔助：名稱解析
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def find_by_name(name: str) -> str:
    """
    根據名稱或 alias 查找對應的設備/群組 ID。
    當你不確定 ID 時，先用這個 tool 查。

    Args:
        name: 中文名稱、alias 或 gateway 原始名稱（如「客廳」、「GC」）
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


# ═══════════════════════════════════════════════════════════════════
# 通知
# ═══════════════════════════════════════════════════════════════════

@mcp.tool()
async def send_notification(message: str) -> str:
    """
    推播訊息到 Telegram（需設定 TELEGRAM_BOT_TOKEN 與 TELEGRAM_CHAT_ID 環境變數）。
    未設定時不報錯，靜默略過。

    典型使用場景：
        - 控制操作後確認通知（「客廳燈已關閉」）
        - 排程執行結果
        - 任何需要主動告知 user 的事件

    Args:
        message: 要傳送的文字訊息

    Returns:
        "已發送" 或 "未設定 Telegram，略過通知"
    """
    sent = await tg_notify(message)
    return "已發送" if sent else "未設定 Telegram，略過通知"


# ═══════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host=MCP_HOST, port=MCP_PORT)
