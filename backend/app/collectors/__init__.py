"""採集適配器包。

導入本包即完成各適配器註冊（registry 見 base.py）。
"""
from app.collectors import beisen, bosera, citics, feishu, greenhouse, gtht, huatai_pb, iguopin, job51, lever, moka, official, workday, zhaopin, zofund  # noqa: F401

__all__ = ["beisen", "bosera", "citics", "feishu", "greenhouse", "gtht", "huatai_pb", "iguopin", "job51", "lever", "moka", "official", "workday", "zhaopin", "zofund"]
