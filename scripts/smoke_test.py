#!/usr/bin/env python
"""部署後冒煙測試：對已部署的後端執行完整用戶旅程。

用法：
  SMOKE_ADMIN_EMAIL=... SMOKE_ADMIN_PASSWORD=... \
  python scripts/smoke_test.py https://jobfly-backend.onrender.com

流程：healthz → 註冊 → me → 設置 → 上傳簡歷 → 解析(LLM) → 畫像(LLM)
      → 添加關注公司 → 採集(Greenhouse 實網) → 匹配評分 → 投遞隊列(off 模式不實際投遞)
"""
import io
import json
import os
import sys
import time
import uuid

import httpx

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else os.environ.get("SMOKE_BASE_URL", "")
if not BASE:
    print("用法: python scripts/smoke_test.py <BACKEND_URL>")
    sys.exit(2)

ADMIN_EMAIL = os.environ.get("SMOKE_ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.environ.get("SMOKE_ADMIN_PASSWORD", "")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail and not ok else ""))


def minimal_pdf() -> bytes:
    return b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj
xref
0 4
trailer<</Size 4/Root 1 0 R>>
%%EOF"""


def resume_text() -> str:
    return """張三 | zhangsan@example.com | 13800138000 | 深圳
教育：華中科技大學 本科 計算機科學 (2014 - 2018)
後端工程師 @ 騰訊 (2018 - 2021)
- 負責微信支付核心交易系統，日均處理千萬級訂單
- 使用 Go/Python 優化結算鏈路，延遲降低 40%
高級後端工程師 @ 字節跳動 (2021 - 至今)
- 主導推薦系統服務化改造，支撐 2 億 DAU
- Kubernetes/Docker 容器化落地，成本下降 30%
技能：Go, Python, Kubernetes, Redis, MySQL, gRPC, 微服務
"""


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=60)

    # 1. healthz
    r = c.get("/healthz")
    check("healthz", r.status_code == 200 and r.json().get("status") == "ok", r.text[:100])

    # 2. 註冊隨機用戶（gmail 域名通過 GoTrue 校驗；若需郵箱確認，降級用管理員帳號繼續）
    email = f"jobfly.smoke.{uuid.uuid4().hex[:8]}@gmail.com"
    token = None
    r = c.post("/api/auth/signup", json={"email": email, "password": "Smoke123456!"})
    if r.status_code == 200 and r.json().get("status") == "ok":
        token = r.json()["session"]["access_token"]
        check("註冊+登錄", True)
    else:
        check("註冊（要求郵箱確認）", r.status_code == 200, r.text[:120])
        if ADMIN_EMAIL:
            r = c.post("/api/auth/signin", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
            if r.status_code == 200:
                token = r.json().get("access_token")
                check("管理員登錄", True)
            else:
                check("管理員登錄", False, r.text[:150])
    if not token:
        print("無法獲取 token，終止")
        sys.exit(1)
    c.headers["Authorization"] = f"Bearer {token}"

    # 3. me（profiles 自動補建）
    r = c.get("/api/me")
    check("GET /api/me", r.status_code == 200 and bool(r.json().get("id")), r.text[:120])

    # 4. 設置
    r = c.patch("/api/me/settings", json={"match_threshold": 50, "auto_apply_mode": "off"})
    ok = r.status_code == 200 and r.json().get("match_threshold") == 50
    check("PATCH 設置（閾值50/off模式）", ok, r.text[:120])

    # 5. 上傳簡歷（TXT，繞開 PDF 解析器）
    r = c.post(
        "/api/documents?doc_type=resume",
        files={"file": ("resume.txt", resume_text().encode("utf-8"), "text/plain")},
    )
    ok = r.status_code == 201
    doc_id = r.json().get("id") if ok else None
    check("上傳簡歷(R2)", ok, r.text[:150])
    if not doc_id:
        sys.exit(1)

    # 6. 解析（LLM）
    r = c.post(f"/api/documents/{doc_id}/parse")
    check("觸發解析", r.status_code == 202, r.text[:150])
    for _ in range(12):
        time.sleep(5)
        r = c.get(f"/api/documents/{doc_id}")
        if r.status_code == 200 and r.json().get("parse_status") in ("parsed", "failed", "ocr"):
            break
    check("解析完成(LLM)", r.json().get("parse_status") == "parsed", str(r.json().get("parse_error", ""))[:120])

    # 7. 畫像（LLM）
    r = c.post("/api/profile/generate", json={})
    check("生成畫像(LLM)", r.status_code == 201, r.text[:150])
    r = c.get("/api/profile")
    check("畫像報表", r.status_code == 200 and bool(r.json().get("summary")), r.text[:120])

    # 8. 關注公司 + 採集（Greenhouse 實網）
    r = c.post("/api/companies", json={
        "company_name": "Cloudflare",
        "careers_url": "https://boards.greenhouse.io/cloudflare",
        "platform": "greenhouse",
    })
    check("添加關注公司", r.status_code == 201, r.text[:150])
    r = c.post("/api/jobs/collect/run")
    ok = r.status_code == 202 and r.json().get("collected", 0) > 0
    check("採集(Greenhouse 實網)", ok, r.text[:200])

    # 9. 崗位庫 + 匹配
    r = c.get("/api/jobs?limit=5")
    check("崗位庫有數據", r.status_code == 200 and len(r.json().get("items", [])) > 0)
    r = c.get("/api/matches")
    scored = [m for m in r.json() if m.get("match_score") is not None]
    check("匹配評分(LLM)", r.status_code == 200 and len(scored) > 0,
          f"已評分 {len(scored)}/{len(r.json())}")

    # 10. 投遞隊列（off 模式：驗證不投遞）
    r = c.post("/api/applications/run")
    ok = r.status_code == 202 and r.json().get("created", {}).get("mode") == "off"
    check("投遞隊列(off模式不投遞)", ok, r.text[:150])
    r = c.get("/api/applications")
    check("投遞記錄接口", r.status_code == 200)

    print("\n========== 結果 ==========")
    failed = [x for x in results if not x[1]]
    for name, ok, _ in results:
        print(f"{'✅' if ok else '❌'} {name}")
    print(f"\n{len(results) - len(failed)}/{len(results)} 通過")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
