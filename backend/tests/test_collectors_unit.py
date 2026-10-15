"""離線單測：適配器 URL 解析與路由（無需網絡/數據庫）。"""
from app.collectors.greenhouse import _parse_board_token
from app.collectors.lever import _parse_site
from app.collectors.official import detect_platform
from app.collectors.workday import _parse_tenant


def test_greenhouse_board_token():
    assert _parse_board_token("https://boards.greenhouse.io/cloudflare") == "cloudflare"
    assert _parse_board_token("https://boards.greenhouse.io/cloudflare/jobs/123") == "cloudflare"
    assert _parse_board_token("https://boards.greenhouse.io/embed/job_board?for=datadog") == "datadog"
    assert _parse_board_token("https://example.com") is None


def test_lever_site():
    assert _parse_site("https://jobs.lever.co/palantir") == "palantir"
    assert _parse_site("https://jobs.lever.co/palantir/1234") == "palantir"
    assert _parse_site("https://example.com") is None


def test_workday_tenant():
    assert _parse_tenant("https://cloudflare.wd1.myworkdayjobs.com/Careers") == (
        "https://cloudflare.wd1.myworkdayjobs.com", "cloudflare", "Careers",
    )
    assert _parse_tenant("https://microsoft.wd1.myworkdayjobs.com/en-US/Microsoft_Careers") == (
        "https://microsoft.wd1.myworkdayjobs.com", "microsoft", "Microsoft_Careers",
    )
    assert _parse_tenant("https://example.com") is None


def test_detect_platform():
    assert detect_platform("https://boards.greenhouse.io/cloudflare") == "greenhouse"
    assert detect_platform("https://jobs.lever.co/palantir") == "lever"
    assert detect_platform("https://x.wd1.myworkdayjobs.com/Careers") == "workday"
    assert detect_platform("https://careers.tencent.com") == "official"
