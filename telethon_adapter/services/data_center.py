from __future__ import annotations

from typing import Any


def format_data_center(value: Any) -> str | None:
    dc_map = {
        1: "🇺🇸 美国迈阿密（DC1）",
        2: "🇳🇱 荷兰阿姆斯特丹（DC2）",
        3: "🇺🇸 美国迈阿密（DC3）",
        4: "🇳🇱 荷兰阿姆斯特丹（DC4）",
        5: "🇸🇬 新加坡（DC5）",
    }
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        dc_id = int(value)
    except (TypeError, ValueError):
        return str(value)
    return dc_map.get(dc_id, f"🌐 未知位置（DC{dc_id}）")
