---
name: tradfri
description: IKEA TRADFRI 智慧家居控制
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
---

# IKEA TRADFRI 燈控

用 exec 執行 `tradfri` 指令，不解釋不確認。

## 指令

```bash
tradfri <名稱> 開
tradfri <名稱> 關
tradfri <名稱> 亮度 <0-100>   # 百分比
tradfri <名稱> 色溫 暖
tradfri <名稱> 色溫 冷
tradfri 查詢 <名稱>
tradfri 列表
```

## 可用名稱

客廳、客廳電視牆、沙發燈、客廳聚光燈、客廳閱讀燈、客廳展示燈、玄關、玄關光條、玄關畫廊、玄關電箱、玄關主燈、融蠟燈、餐廳、餐桌燈、餐廳軌道燈、主臥室、次臥室、走道燈、衣櫥燈、立燈、小夜燈

## 規則

- 直接執行，不解釋，不詢問
- 「關閉/熄/關掉」→ 關；「開啟/打開/開燈」→ 開
- 「電視牆燈」→ 客廳電視牆
- 「全部燈」→ 依序對每個名稱執行
- 不知道名稱時先 `tradfri 列表`
- 執行後只回報結果
