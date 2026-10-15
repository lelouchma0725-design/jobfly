#!/usr/bin/env python
"""Render 全自動部署：後端 Docker Web Service（美區）+ 前端靜態站。

密鑰從 backend/.env 讀取，通過 API 注入環境變量（不入代碼倉庫）。
"""
import os
import re
import sys
import time

import httpx

RENDER_TOKEN = os.environ["RENDER_TOKEN"]
REPO = "https://github.com/lelouchma0725-design/jobfly"
BRANCH = "main"

api = httpx.Client(
    base_url="https://api.render.com/v1",
    headers={"Authorization": f"Bearer {RENDER_TOKEN}", "Content-Type": "application/json"},
    timeout=60,
)


def env_from_dotenv(path: str) -> dict[str, str]:
    out = {}
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def main() -> None:
    # ownerId
    owners = api.get("/owners").json()
    if not owners:
        print("無 owner：Render API Key 可能無效")
        sys.exit(1)
    owner_id = owners[0]["owner"]["id"] if "owner" in owners[0] else owners[0]["id"]
    print("owner:", owner_id)

    env = env_from_dotenv("backend/.env")
    backend_envs = [
        {"key": "SUPABASE_URL", "value": env["SUPABASE_URL"]},
        {"key": "SUPABASE_ANON_KEY", "value": env["SUPABASE_ANON_KEY"]},
        {"key": "SUPABASE_SERVICE_ROLE_KEY", "value": env["SUPABASE_SERVICE_ROLE_KEY"]},
        {"key": "DATABASE_URL", "value": env["DATABASE_URL"]},
        {"key": "KEK_BASE64", "value": env["KEK_BASE64"]},
        {"key": "R2_ACCOUNT_ID", "value": env["R2_ACCOUNT_ID"]},
        {"key": "R2_ACCESS_KEY_ID", "value": env["R2_ACCESS_KEY_ID"]},
        {"key": "R2_SECRET_ACCESS_KEY", "value": env["R2_SECRET_ACCESS_KEY"]},
        {"key": "R2_BUCKET", "value": env["R2_BUCKET"]},
        {"key": "LLM_BASE_URL", "value": env["LLM_BASE_URL"]},
        {"key": "LLM_API_KEY", "value": env["LLM_API_KEY"]},
        {"key": "LLM_MODEL", "value": env["LLM_MODEL"]},
        {"key": "ADMIN_EMAILS", "value": "chinasnhmxy@hotmail.com"},
        {"key": "APP_ENV", "value": "prod"},
        {"key": "FRONTEND_URL", "value": "https://PLACEHOLDER-FRONTEND.onrender.com"},
        {"key": "PUBLIC_BASE_URL", "value": "https://PLACEHOLDER-BACKEND.onrender.com"},
        {"key": "PLAYWRIGHT_BROWSERS_PATH", "value": "/ms-playwright"},
    ]

    # 後端
    r = api.post(
        "/services",
        json={
            "type": "web_service",
            "name": "jobfly-backend",
            "ownerId": owner_id,
            "repo": REPO,
            "branch": BRANCH,
            "region": "ohio",
            "plan": "free",
            "serviceDetails": {
                "env": "docker",
                "dockerfilePath": "./backend/Dockerfile",
                "dockerContext": "./backend",
            },
            "envVars": backend_envs,
        },
    )
    print("backend create:", r.status_code, r.text[:400])
    if r.status_code >= 400:
        sys.exit(1)
    backend_svc = r.json()
    backend_id = backend_svc["service"]["id"] if "service" in backend_svc else backend_svc["id"]

    # 前端
    r = api.post(
        "/services",
        json={
            "type": "static_site",
            "name": "jobfly-frontend",
            "ownerId": owner_id,
            "repo": REPO,
            "branch": BRANCH,
            "serviceDetails": {
                "buildCommand": "npm install --prefix frontend && npm run build --prefix frontend",
                "publishPath": "frontend/dist",
            },
        },
    )
    print("frontend create:", r.status_code, r.text[:400])
    if r.status_code >= 400:
        sys.exit(1)
    front_svc = r.json()
    frontend_id = front_svc["service"]["id"] if "service" in front_svc else front_svc["id"]

    # 等待獲取 URL
    for _ in range(30):
        time.sleep(10)
        b = api.get(f"/services/{backend_id}").json()
        f = api.get(f"/services/{frontend_id}").json()
        bsd = (b.get("service") or {}).get("serviceDetails") or {}
        fsd = (f.get("service") or {}).get("serviceDetails") or {}
        b_url = bsd.get("url")
        f_url = fsd.get("url")
        if b_url and f_url:
            break
    else:
        print("未能獲取 URL，手動查 Dashboard")
        sys.exit(1)

    print("backend:", b_url)
    print("frontend:", f_url)

    # 回填跨域與推送連結
    updated = [e for e in backend_envs if e["key"] not in ("FRONTEND_URL", "PUBLIC_BASE_URL")]
    updated += [{"key": "FRONTEND_URL", "value": f_url}, {"key": "PUBLIC_BASE_URL", "value": b_url}]
    r = api.put(f"/services/{backend_id}/env-vars", json=updated)
    print("backend env update:", r.status_code)
    r = api.post(f"/services/{backend_id}/deploys")
    print("backend redeploy:", r.status_code)

    print("✅ 部署完成")
    print(f"  後端:   {b_url}  (/healthz)")
    print(f"  前端:   {f_url}")


if __name__ == "__main__":
    main()
