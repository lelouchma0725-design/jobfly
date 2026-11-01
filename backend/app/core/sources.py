"""來源（招聘平台）標籤映射：採集器代碼 → 用戶可讀的平台名。"""
from __future__ import annotations

SOURCE_LABELS: dict[str, str] = {
    "iguopin": "國聘",
    "official": "公司官網",
    "citics": "公司官網",
    "gtht": "公司官網",
    "zofund": "公司官網",
    "huatai_pb": "公司官網",
    "beisen": "北森招聘雲",
    "bosera": "北森招聘雲",
    "feishu": "飛書招聘",
    "moka": "Moka招聘",
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "workday": "Workday",
    "generic": "公司官網",
}


def source_label(code: str | None) -> str:
    return SOURCE_LABELS.get(code or "", code or "未知")
