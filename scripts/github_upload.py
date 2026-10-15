#!/usr/bin/env python
"""通過 GitHub API 上傳整個倉庫（github.com git 端口被封時的繞行方案）。

流程：contents API 初始化 README（空倉庫首次提交）→ blobs → tree → commit → 更新 ref。
"""
import base64
import os
import subprocess

import httpx

TOKEN = os.environ["GH_TOKEN"]
OWNER, REPO = "lelouchma0725-design", "jobfly"

api = httpx.Client(
    base_url="https://api.github.com",
    headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json"},
    timeout=60,
)

# 1) 初始化空倉庫：README 首次提交（自動建 main 分支）
r = api.get(f"/repos/{OWNER}/{REPO}/git/ref/heads/main")
if r.status_code == 200:
    base_commit_sha = r.json()["object"]["sha"]
    print("main 已存在:", base_commit_sha[:12])
else:
    readme = base64.b64encode("# JobFly 求職簡歷自動投遞系統\n".encode()).decode()
    r = api.put(
        f"/repos/{OWNER}/{REPO}/contents/README.md",
        json={"message": "init: JobFly", "content": readme},
    )
    r.raise_for_status()
    base_commit_sha = r.json()["commit"]["sha"]
    print("init commit:", base_commit_sha[:12])

base_commit = api.get(f"/repos/{OWNER}/{REPO}/git/commits/{base_commit_sha}").json()
base_tree_sha = base_commit["tree"]["sha"]

# 2) 全部文件 → blobs → tree
files = [f for f in subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\x00") if f]
print(f"共 {len(files)} 個文件")
tree_items = []
for i, f in enumerate(files, 1):
    content = base64.b64encode(open(f, "rb").read()).decode()
    r = api.post(f"/repos/{OWNER}/{REPO}/git/blobs", json={"content": content, "encoding": "base64"})
    r.raise_for_status()
    tree_items.append({"path": f, "mode": "100644", "type": "blob", "sha": r.json()["sha"]})
    if i % 20 == 0:
        print(f"  blobs {i}/{len(files)}")

r = api.post(f"/repos/{OWNER}/{REPO}/git/trees", json={"base_tree": base_tree_sha, "tree": tree_items})
r.raise_for_status()
tree_sha = r.json()["sha"]
print("tree:", tree_sha[:12])

# 3) 提交並推進 main
r = api.post(
    f"/repos/{OWNER}/{REPO}/git/commits",
    json={
        "message": "JobFly 求職簡歷自動投遞系統：P0-P5 全模塊 + 認證代理",
        "tree": tree_sha,
        "parents": [base_commit_sha],
    },
)
r.raise_for_status()
commit_sha = r.json()["sha"]
r = api.patch(f"/repos/{OWNER}/{REPO}/git/refs/heads/main", json={"sha": commit_sha})
r.raise_for_status()
print("✅ 完成:", f"https://github.com/{OWNER}/{REPO}", "| commit", commit_sha[:12])
