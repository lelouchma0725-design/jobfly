"""實網測試（默認跳過；RUN_LIVE=1 pytest tests/test_collectors_live.py 啟用）。"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE") != "1", reason="實網測試需 RUN_LIVE=1"
)


def test_greenhouse_live():
    from app.collectors.greenhouse import GreenhouseCollector

    posts = GreenhouseCollector().collect(
        {"company_name": "Cloudflare", "careers_url": "https://boards.greenhouse.io/cloudflare"}
    )
    assert len(posts) > 50
    assert len({p.external_id for p in posts}) == len(posts)  # 去重鍵唯一
    assert any(p.description_text for p in posts)             # 至少抓到部分 JD


def test_lever_live():
    from app.collectors.lever import LeverCollector

    posts = LeverCollector().collect(
        {"company_name": "Palantir", "careers_url": "https://jobs.lever.co/palantir"}
    )
    assert len(posts) > 50
    assert posts[0].title and posts[0].description_text


def test_workday_live():
    """注意：Workday 對部分地區 IP 有封鎖（R10），此測試在美區部署環境跑。"""
    from app.collectors.workday import WorkdayCollector

    posts = WorkdayCollector().collect(
        {"company_name": "Microsoft",
         "careers_url": "https://microsoft.wd1.myworkdayjobs.com/Microsoft_Careers"}
    )
    assert len(posts) > 20
