"""前程無憂（51job）採集器。

接口（2026-11 抓包實測）：
- 列表：GET https://we.51job.com/api/job/search-pc
  參數：api_key=51job&timestamp={ts}&keyword={kw}&searchType=2&jobArea={code}
        &pageNum={n}&pageSize=20&source=1&scene=7
- 防護：阿里雲 WAF——需要先在瀏覽器中打開搜索頁獲得 cookie，
  之後在頁面上下文內用 fetch 調 API（Playwright 驅動）。
- 響應：resultbody.job.{items:[{jobId,jobName,companyName,fullCompanyName,
  provideSalaryString,jobAreaString,workAreaCode,jobDescribe,workYearString,
  degreeString,isIntern,issueDateString}], totalCount}

過濾策略：
- 城市：北京(010000)、上海(020000)（香港職位大陸站極少，以 jobArea 為主）
- 薪資：本地解析 provideSalaryString，區間上限 ≥ 1.5萬/月（或年薪 ≥ 18萬）
- 關鍵詞：用戶畫像相關（數據分析/量化/金融科技/行業研究/商業分析）
"""
from __future__ import annotations

import logging
import re

from app.collectors.base import JobPosting, register

logger = logging.getLogger(__name__)

COMPANY = "前程無憂"
KEYWORDS = ("数据分析", "量化研究", "金融科技", "行业研究", "商业分析")
AREAS = (("010000", "北京"), ("020000", "上海"))
PAGES_PER_KEYWORD = 5  # 每關鍵詞 5 頁（100 個），控制時長
HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
}


def _salary_ok(text: str | None) -> bool:
    """薪資上限 ≥ 1.5萬/月 或 年薪 ≥ 18萬。"""
    if not text:
        return False
    t = text.replace("·", " ").replace(",", "")
    m = re.search(r"([\d.]+)\s*-\s*([\d.]+)\s*万", t)  # 月薪（萬）
    if m:
        return float(m.group(2)) >= 1.5
    m = re.search(r"([\d.]+)\s*万", t)
    if m:
        return float(m.group(1)) >= 1.5
    m = re.search(r"([\d.]+)\s*-\s*([\d.]+)\s*千", t)  # 月薪（千）
    if m:
        return float(m.group(2)) >= 15
    m = re.search(r"([\d.]+)\s*-\s*([\d.]+)\s*万/年", t)  # 年薪
    if m:
        return float(m.group(2)) >= 18
    return False


_JS_FETCH = """
async (kw, area, pageNum) => {
  const ts = Math.floor(Date.now() / 1000);
  const url = 'https://we.51job.com/api/job/search-pc?api_key=51job&timestamp=' + ts +
    '&keyword=' + encodeURIComponent(kw) + '&searchType=2&function=&industry=&jobArea=' + area +
    '&jobArea2=&landmark=&metro=&salary=&workYear=&degree=&companyType=&companySize=' +
    '&jobType=&issueDate=&sortType=0&pageNum=' + pageNum + '&requestId=&pageSize=20&source=1' +
    '&accountId=&pageCode=sou%7Csou%7Csoulb&scene=7';
  const resp = await fetch(url, {headers: {'Accept': 'application/json'}});
  const t = await resp.text();
  try { return JSON.parse(t); } catch { return {error: t.slice(0, 150)}; }
}
"""


@register
class Job51Collector:
    name = "job51"

    def collect(self, target: dict) -> list[JobPosting]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:  # pragma: no cover
            logger.warning("job51 需要 Playwright")
            return []

        postings: list[JobPosting] = []
        seen: set[str] = set()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=HEADERS_BASE["User-Agent"], locale="zh-CN")
            page = ctx.new_page()
            captured: list[list[dict]] = []

            def on_response(resp):
                if "search-pc" in resp.url and resp.status == 200:
                    try:
                        d = resp.json()
                        rb = d.get("resultbody") or {}
                        job = rb.get("job") or {}
                        items = job.get("items") or []
                        if items:
                            captured.append(items)
                    except Exception:  # noqa: BLE001
                        pass

            page.on("response", on_response)
            try:
                for kw in KEYWORDS:
                    for area_code, area_name in AREAS:
                        for pnum in range(1, PAGES_PER_KEYWORD + 1):
                            captured.clear()
                            from urllib.parse import quote

                            try:
                                # 頁面自身發起的請求會自動帶 WAF 簽名參數，攔截其響應
                                page.goto(
                                    f"https://we.51job.com/pc/search?keyword={quote(kw)}"
                                    f"&searchType=2&sortType=0&metro=&jobArea={area_code}"
                                    f"&pageNum={pnum}",
                                    wait_until="domcontentloaded", timeout=30000,
                                )
                                page.wait_for_timeout(9000)
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("job51 導航失敗 kw=%s p=%s: %s", kw, pnum, exc)
                                break
                            if not captured:
                                break
                            items = captured[0]
                            for it in items:
                                key = str(it.get("jobId") or "")
                                if not key or key in seen:
                                    continue
                                if not _salary_ok(it.get("provideSalaryString")):
                                    continue
                                seen.add(key)
                                title = str(it.get("jobName") or "").strip()
                                desc = str(it.get("jobDescribe") or "")[:6000]
                                postings.append(JobPosting(
                                    source="job51",
                                    external_id=key,
                                    company_name=str(it.get("fullCompanyName") or it.get("companyName") or COMPANY),
                                    title=title,
                                    apply_url=str(it.get("jobHref") or "https://we.51job.com/pc/search"),
                                    location=area_name or None,
                                    department=None,
                                    description_text=desc,
                                    posted_at=str(it.get("issueDateString") or "") or None,
                                    raw={
                                        "tab": "校園招聘" if (it.get("isIntern") or "校" in title) else "社會招聘",
                                        "is_campus": bool(it.get("isIntern")) or "校" in title,
                                        "is_intern": bool(it.get("isIntern")),
                                        "salary": it.get("provideSalaryString"),
                                        "work_year": it.get("workYearString"),
                                        "degree": it.get("degreeString"),
                                        **it,
                                    },
                                ))
            finally:
                browser.close()
        return postings
