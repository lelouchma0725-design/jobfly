#!/usr/bin/env bash
# JobFly 開發環境一鍵安裝（macOS arm64，DeepSeek Harness 環境驗證通過）
#
# 本環境有兩個坑，腳本已自動處理：
# 1. DSH 捆綁的 Python/Node 均為團隊簽名 + 硬化運行時，拒絕加載 PyPI/npm
#    上的第三方簽名二進制（"different Team IDs"）。
#    → Python 用 uv 管理的解釋器（ad-hoc 簽名）；Node 用官方 tarball 並 ad-hoc 重簽。
# 2. pnpm 11 默認攔截構建腳本（esbuild），需 pnpm-workspace.yaml 的 allowBuilds。
set -euo pipefail
cd "$(dirname "$0")/.."

echo "== 1/3 後端：uv 虛擬環境 =="
cd backend
if ! command -v uv >/dev/null 2>&1; then
  echo "缺少 uv，安裝中…"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
export UV_CACHE_DIR="$PWD/../.uv-cache"
export UV_PYTHON_INSTALL_DIR="$PWD/../.uv-python"
uv venv .venv --python 3.12
uv pip install -e ".[dev,automation]"
# Playwright 瀏覽器裝到工作區（避免寫系統目錄 + 沙箱限制）
export PLAYWRIGHT_BROWSERS_PATH="$PWD/../.playwright-browsers"
./.venv/bin/playwright install chromium
./.venv/bin/python -c "from app.main import app; print('  後端 import OK，路由數:', len(app.routes))"

echo "== 2/3 前端：Node 22（ad-hoc 重簽）=="
cd ../.tooling
if [ ! -x node22/bin/node ]; then
  curl -sL -o node.tar.gz https://nodejs.org/dist/latest-v22.x/node-v22.23.3-darwin-arm64.tar.gz
  tar -xzf node.tar.gz
  mv node-v22.23.3-darwin-arm64 node22
  xattr -d com.apple.quarantine node22/bin/node 2>/dev/null || true
  codesign -s - node22/bin/node   # ad-hoc 重簽（未簽名的 arm64 二進制會被系統直接殺掉）
fi
export PATH="$PWD/node22/bin:$PATH"

echo "== 3/3 前端依賴與構建 =="
cd ../frontend
node "$(dirname "$(command -v node)")/../" 2>/dev/null || true
# pnpm.mjs 需要 node 解釋器運行
node /Users/harryma/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/pnpm/bin/pnpm.mjs install --no-frozen-lockfile
node /Users/harryma/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/pnpm/bin/pnpm.mjs run build
echo "全部完成 ✅"
echo "下一步：cp backend/.env.example backend/.env 填入配置，然後 alembic upgrade head"
