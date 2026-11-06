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
    "job51": "前程無憂",
    "zhaopin": "智聯招聘",
    "jobsdb": "JobsDB",
    "ctgoodjobs": "CTgoodjobs",
    "liepin": "獵聘",
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "workday": "Workday",
    "generic": "公司官網",
}


def source_label(code: str | None) -> str:
    return SOURCE_LABELS.get(code or "", code or "未知")

def resolve_source(text: str | None) -> str | None:
    """來源參數解析：支持代碼（iguopin）、完整標籤（國聘）、模糊標籤（智聯→智聯招聘）。"""
    t = (text or "").strip()
    if not t:
        return None
    if t in SOURCE_LABELS:
        return t
    for code, label in SOURCE_LABELS.items():
        if label == t:
            return code
    for code, label in SOURCE_LABELS.items():
        if t in label:
            return code
    return t  # 未知值原樣傳回（後端 WHERE 不命中自然為空）
