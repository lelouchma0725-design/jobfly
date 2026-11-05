"""生成软著源程序 docx（精簡版）。

精簡內容：
- 移除 RPA 瀏覽器擴展（chrome-extension/、api/rpa.py）
- 移除多平台採集適配器（beisen/citics/gtht/greenhouse/lever/workday），僅保留通用官網採集框架
- 移除客戶端 E2EE（lib/crypto.ts 及前端密鑰派生），敏感字段改為服務端 AES-GCM 欄位加密

排版：A4 / Courier New 8.5pt / 固定行距 232twips / 每頁 50 行 / 硬分頁 / 共 60 頁 3000 行
"""
from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.enum.text import WD_BREAK
from docx.shared import Emu, Pt

REPO = Path("/Users/harryma/DeepSeekHarness/.work/jobfly")

LINES_PER_PAGE = 50
TOTAL_PAGES = 60
TOTAL_LINES = LINES_PER_PAGE * TOTAL_PAGES  # 3000

# 檔案順序：app 包 → api（字母序）→ core → services
FILES = [
    "backend/app/__init__.py",
    "backend/app/api/__init__.py",
    "backend/app/api/accounts.py",
    "backend/app/api/applications.py",
    "backend/app/api/auth.py",
    "backend/app/api/companies.py",
    "backend/app/api/info_fields.py",
    "backend/app/api/jobs.py",
    "backend/app/api/matches.py",
    "backend/app/api/tasks.py",
    "backend/app/core/auth.py",
    "backend/app/core/security.py",
    "backend/app/core/audit.py",
    "backend/app/core/r2.py",
    "backend/app/core/llm.py",
    "backend/app/core/scheduler.py",
    "backend/app/apply/generic_apply.py",
    "backend/app/services/matching.py",
    "backend/app/services/apply_engine.py",
]



# 精簡版同步修訂：去掉 RPA 擴展 / 客戶端 E2EE 的殘留表述
PATCHES: dict[str, str] = {}

def collect_lines() -> tuple[list[str], list[tuple[str, int]]]:
    """按檔案順序攤平代碼行，截斷到 TOTAL_LINES。"""
    out: list[str] = []
    used: list[tuple[str, int]] = []
    for rel in FILES:
        if len(out) >= TOTAL_LINES:
            break
        text = (REPO / rel).read_text(encoding="utf-8")
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines = lines[:-1]
        take = lines[: TOTAL_LINES - len(out)]
        out.extend(PATCHES.get(x, x) for x in take)
        used.append((rel, len(take)))
    return out, used


def _fmt_paragraph(para, line: str) -> None:
    ppr = para._p.get_or_add_pPr()
    sp = ppr.makeelement(qn("w:spacing"), {})
    sp.set(qn("w:lineRule"), "exact")
    sp.set(qn("w:line"), "232")
    sp.set(qn("w:before"), "0")
    sp.set(qn("w:after"), "0")
    ppr.append(sp)
    run = para.add_run(line)
    run.font.name = "Courier New"
    run.font.size = Pt(8.5)
    r = run._element.get_or_add_rPr()
    rf = r.find(qn("w:rFonts"))
    if rf is None:
        rf = r.makeelement(qn("w:rFonts"), {})
        r.append(rf)
    rf.set(qn("w:ascii"), "Courier New")
    rf.set(qn("w:hAnsi"), "Courier New")
    rf.set(qn("w:eastAsia"), "宋体")


def build(out_path: str) -> None:
    lines, used = collect_lines()
    assert len(lines) == TOTAL_LINES, f"行數不足: {len(lines)}"

    doc = Document()
    sec = doc.sections[0]
    sec.page_width = Emu(7560310)
    sec.page_height = Emu(10692130)
    sec.left_margin = Emu(647700)
    sec.right_margin = Emu(647700)
    sec.top_margin = Emu(539750)
    sec.bottom_margin = Emu(539750)

    normal = doc.styles["Normal"]
    normal.font.name = "Courier New"
    normal.font.size = Pt(8.5)
    rpr = normal.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.append(rfonts)
    rfonts.set(qn("w:ascii"), "Courier New")
    rfonts.set(qn("w:hAnsi"), "Courier New")
    rfonts.set(qn("w:eastAsia"), "宋体")

    for i, line in enumerate(lines):
        para = doc.add_paragraph()
        _fmt_paragraph(para, line)
        if (i + 1) % LINES_PER_PAGE == 0 and i + 1 < TOTAL_LINES:
            br = doc.add_paragraph()
            br.add_run().add_break(WD_BREAK.PAGE)

    doc.save(out_path)
    print(f"lines={len(lines)} pages={TOTAL_PAGES}")
    for rel, n in used:
        print(f"  {n:5d}  {rel}")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/Users/harryma/DeepSeekHarness/.tmp_resume/out/source_lite.docx"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    build(out)
