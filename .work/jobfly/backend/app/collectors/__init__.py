"""採集適配器包。

精簡版只保留一個通用官網採集器（official）：
按 careers_url 用瀏覽器啟發式採集崗位鏈接與標題，不再維護各招聘平台的定制抓包適配器。
導入本包即完成註冊（registry 見 base.py）。
"""
from app.collectors import official  # noqa: F401

__all__ = ["official"]
