# JobFly — 求職簡歷自動投遞系統

多租戶 Web/SaaS 平台：用戶上傳簡歷與文件、配置投遞策略，系統每日自動採集關注公司崗位、按貼合度匹配、自動投遞（公司官網/國際 ATS），並通過微信/郵箱推送結果；遇到驗證碼或缺失信息時推送用戶人工接管，回填後自動繼續。

## 倉庫結構

```
docs/                 設計文檔（需求規格/架構/數據模型/免費服務選型/路線圖）
backend/              Python 3.12 + FastAPI
  app/
    api/              REST 端點（me/documents/accounts/companies/profile/matches/jobs/applications/tasks）
    apply/            投遞適配器（greenhouse/lever/generic + Playwright 工具）
    collectors/       採集適配器（greenhouse/lever/workday/official + 流水線）
    services/         解析/畫像/匹配/投遞引擎/通知/摘要
    core/             認證/信封加密/LLM/調度器/R2
  alembic/            數據庫遷移（0001_initial = 全部 19 張表 + RLS）
frontend/             React 18 + Vite + TypeScript（登錄/崗位庫/匹配/投遞記錄/待處理/文件/畫像/設置）
scripts/              一鍵開發環境安裝
```

## 快速開始

### 0. 前置準備（見 docs/04-路線圖.md 第 4 節）

1. Supabase 項目（拿到 URL、anon key、service_role key、Postgres 連接串）
2. Cloudflare R2 桶 + API Token（存附件）
3. LLM API key（DeepSeek 等 OpenAI 兼容接口）
4. 推送渠道：PushPlus token / 企業微信 webhook / SMTP

### 1. 一鍵安裝開發環境

```bash
bash scripts/setup-dev.sh
```

> macOS（DeepSeek Harness 環境）注意：捆綁的 Python/Node 為團隊簽名硬化二進制，
> 拒絕加載第三方簽名的原生模塊。腳本已處理：Python 用 uv 管理的解釋器，
> Node 用官方 v22 tarball 並 ad-hoc 重簽（見腳本註釋）。

### 2. 後端

```bash
cd backend
cp .env.example .env        # 填入 Supabase 等配置
openssl rand -base64 32     # 生成 KEK_BASE64
alembic upgrade head        # 初始化數據庫（管理員操作）
uvicorn app.main:app --reload
```

### 3. 前端

```bash
cd frontend
cp .env.example .env        # 填入 VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY
# 用 setup-dev.sh 安裝好的 Node：
PATH="$(pwd)/../.tooling/node22/bin:$PATH" node /Users/harryma/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/pnpm/bin/pnpm.mjs run dev
# → http://localhost:5173
```

## 設計文檔

- [00-需求規格](docs/00-需求規格.md) — 功能映射、查漏補缺（GAP-1~12）、非功能需求
- [01-架構設計](docs/01-架構設計.md) — 模塊、關鍵流程（採集/評分/投遞狀態機/人工接管）、安全
- [02-數據模型](docs/02-數據模型.md) — 19 張表、RLS 策略、索引
- [03-免費服務選型](docs/03-免費服務選型.md) — 已核實的免費額度與推送渠道
- [04-路線圖](docs/04-路線圖.md) — P0~P6 階段進度、風險登記冊、需你配合的事項
- [05-部署運維](docs/05-部署運維.md) — Supabase/R2/Render 部署步驟、保活、上線檢查清單
- [06-法律文件草案](docs/06-法律文件草案.md) — 用戶協議/隱私政策/代投授權書要點（上線前需律師審）

## 重要部署注意（實測發現）

- **Workday 等 ATS 有區域 IP 封鎖**：本機網絡訪問 *.myworkdayjobs.com 被 302 到維護頁。
  採集/投遞 Worker 必須部署在美區（Render/Railway 選 US region），否則 Workday 採集不可用。
- Playwright 瀏覽器路徑建議設 `PLAYWRIGHT_BROWSERS_PATH` 指向工作區/持久盤。

## 安全提醒

- `SUPABASE_SERVICE_ROLE_KEY`、`DATABASE_URL`、`KEK_BASE64` 只存後端環境變量，**絕不**提交到倉庫或暴露給前端。
- 第三方平台帳密使用信封加密存儲（AES-256-GCM），明文永不落庫。
