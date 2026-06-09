---
name: tradfri
description: IKEA TRADFRI smart home light control
author: local
version: 2.0.0
triggers:
  - "開燈"
  - "關燈"
  - "調光"
  - "調亮"
  - "調暗"
  - "色溫"
  - "IKEA"
  - "tradfri"
  - "燈"
  - "turn on"
  - "turn off"
  - "dim"
  - "brighten"
  - "lights"
  - "colour temp"
  - "color temp"
---

# IKEA TRADFRI light control

Execute `tradfri` commands via exec — no explanation, no confirmation.

## Commands

```bash
tradfri <name> 開        # on
tradfri <name> 關        # off
tradfri <name> 亮度 <0-100>   # brightness (percent)
tradfri <name> 色溫 暖   # warm colour temp
tradfri <name> 色溫 冷   # cool colour temp
tradfri 查詢 <name>      # query status
tradfri 列表             # list all names
```

## Available names

客廳、客廳電視牆、沙發燈、客廳聚光燈、客廳閱讀燈、客廳展示燈、玄關、玄關光條、玄關畫廊、玄關電箱、玄關主燈、融蠟燈、餐廳、餐桌燈、餐廳軌道燈、主臥室、次臥室、走道燈、衣櫥燈、立燈、小夜燈

## Rules

- Execute immediately — no explanation, no confirmation
- 「關閉/熄/關掉」→ 關；「開啟/打開/開燈」→ 開
- 「電視牆燈」→ 客廳電視牆
- 「全部燈」→ run command for every name in sequence
- If name is unknown, run `tradfri 列表` first
- After execution, report result only
