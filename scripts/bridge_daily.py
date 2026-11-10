"""本地橋接常駐採集：每天跑一輪前程無憂 + 智聯（海外服務器被風控，統一本地橋接）。

用法（本地環境，需 Playwright 瀏覽器）：
    cd backend && export PLAYWRIGHT_BROWSERS_PATH=/Users/harryma/DeepSeekHarness/.playwright-browsers
    ./.venv/bin/python ../scripts/bridge_daily.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from sqlalchemy import text  # noqa: E402

from app.collectors.iguopin import IguopinCollector  # noqa: E402
from app.collectors.job51 import Job51Collector  # noqa: E402
from app.collectors.pipeline import store_postings  # noqa: E402
from app.collectors.zhaopin import ZhaopinCollector  # noqa: E402
from app.db import SessionLocal  # noqa: E402


def run(name: str, collector) -> None:
    try:
        posts = collector.collect({"company_name": name})
    except Exception as exc:  # noqa: BLE001
        print(f"[{name}] 採集失敗: {exc}")
        return
    db = SessionLocal()
    try:
        stats = store_postings(db, posts)
        db.commit()
        cur = db.execute(
            text("SELECT count(*) FROM job_postings WHERE source=:s AND is_active=true"),
            {"s": posts[0].source if posts else "?"},
        ).scalar()
    finally:
        db.close()
    tabs = dict(Counter(p.raw.get("tab") for p in posts))
    print(f"[{name}] 採集 {len(posts)} 個 {tabs} | 入庫 {stats} | 在庫 {cur}")


if __name__ == "__main__":
    run("國聘", IguopinCollector())
    run("智聯招聘", ZhaopinCollector())
    run("前程無憂", Job51Collector())
    print("橋接採集完成")
