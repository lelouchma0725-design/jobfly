"""生成精簡版用戶手冊 docx（保持原文件排版：宋体 11pt / Heading 2 / A4）。"""
from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Emu, Pt, RGBColor

TITLE = "基于大数据分析的求职简历智能匹配投递系统V0.5"
SUBTITLE = "用户手册"

# (標題, [正文段落...])
SECTIONS: list[tuple[str, list[str]]] = [
    (
        "系统登录",
        [
            "在浏览器中打开系统网址 https://jobscoming-frontend.onrender.com ，进入登录界面。"
            "输入注册时的邮箱与密码，点击登录按钮进入系统。登录成功后系统签发短期访问令牌并自动续期，"
            "令牌仅保存在当前浏览器会话中，退出登录即失效。",
            "用户也可以点击「发送邮箱登录链接」，通过邮件中的一次性登录链接完成登录。"
            "系统部署于云端免费实例，空闲时会休眠，首次点击登录后若提示「正在唤醒服务器」，"
            "请等待10-30秒后重试即可。",
        ],
    ),
    (
        "首页（AI求职管家）",
        [
            "登录后进入系统首页，首页内嵌 AI 求职管家聊天窗口。用户用自然语言即可完成求职全流程操作，"
            "例如输入「帮我采集并匹配中金公司的岗位」，管家会自动发现招聘官网、添加关注公司、"
            "后台采集岗位并生成匹配结果。",
            "管家支持的操作包括：岗位采集、匹配评分查询、投递申请、进度查询、信息补全指引等。"
            "当任务需要人工参与（如短信验证码、图形验证码）时，管家会明确告知缺少的信息和补全步骤，"
            "并生成待处理任务。",
        ],
    ),
    (
        "我的资料",
        [
            "「我的资料」页面集中管理求职所需全部个人信息，包含以下板块："
            "基本信息（姓名、手机、邮箱）；"
            "个人表单信息库（投递时自动互补的表单问答数据，敏感字段以密文存储并打码显示）；"
            "关注公司（添加要采集招聘信息的公司及其招聘官网）；"
            "简历文件（上传简历附件，存储于云端对象存储，通过预签名链接安全下载）；"
            "AI 画像（由简历自动生成的结构化求职画像）；"
            "投递设置（投递模式、每日投递上限、期望城市与校园/社会招聘偏好）；"
            "安全中心（修改密码）。",
        ],
    ),
    (
        "匹配与岗位",
        [
            "「匹配与岗位」页面展示系统对你与各岗位的匹配结果。每条记录包含岗位名称、公司、地点、"
            "类型（校招/社招/实习）、来源（公司招聘官网）、贴合度与优先级两个分数。"
            "贴合度代表岗位与个人条件的匹配程度，优先级在贴合度基础上叠加地区、校招职级、总部分支等偏好加权，"
            "用于决定投递顺序。",
            "页面支持按公司、状态、类型、来源进行筛选与搜索（支持简体中文、繁体中文与英文），"
            "可展开查看单项的贴合度分析、各方向分数与硬性条件说明，并可对单公司或全部岗位重新匹配。",
        ],
    ),
    (
        "岗位库",
        [
            "「岗位库」页面展示系统采集到的全部岗位信息，支持按公司、类型、来源筛选与关键词搜索。"
            "页面顶部显示采集状态（进行中/完成/本次新增数），并提供「立即采集」按钮按公司或全部关注公司手动触发采集。",
            "系统每日凌晨02:00自动采集全部关注公司招聘官网的最新岗位并自动匹配新岗位。"
            "招聘已结束的岗位会保留在岗位库中并标记「已结束」，同时自动从匹配列表中消失，"
            "实现数据的滚动更新。",
        ],
    ),
    (
        "投递管理",
        [
            "「投递管理」页面管理自动投递队列与投递单。系统按优先级顺序创建投递任务，"
            "对所有招聘官网使用同一套通用表单填写逻辑：自动识别姓名、邮箱、手机、城市、薪资、"
            "到岗时间等常见字段并填写，上传简历附件，随后尝试提交。",
            "若提交结果可以确认成功，系统直接将投递记录为已投递；若遇到验证码、必填字段缺少数据，"
            "或无法确认提交结果，系统不会自行猜测或反复重试，而是生成「待确认」任务，"
            "任务中附有官方申请链接、已填写字段摘要与完整填写方案。",
        ],
    ),
    (
        "填表资料一键复制",
        [
            "对于需要人工处理的申请，系统在「待处理/待确认」任务中提供「填写方案」："
            "按当前资料整理好的姓名、手机、邮箱、签证状态、期望薪资、可到岗时间、技能、"
            "工作经历与教育等栏目内容，点击「一键复制填写方案」即可整段复制到剪贴板。",
            "用户在招聘官网对应栏位逐一粘贴、上传简历附件并提交后，回到任务勾选确认并填写申请编号，"
            "系统即记录投递状态为已投递，不再重复投递。填写方案随资料库更新实时重新生成，"
            "不依赖任何浏览器插件，也无需在本地安装额外程序。",
        ],
    ),
    (
        "通知与每日任务",
        [
            "系统每日凌晨02:00执行自动采集任务并留存任务日志；新岗位自动进入匹配评分流程。"
            "用户可在「投递设置」中配置每日推送时间，系统将匹配结果与投递进展以邮件摘要形式推送。",
        ],
    ),
    (
        "隐私与安全",
        [
            "系统采用多租户数据隔离与多层隐私保护：全部业务数据按用户标识隔离，跨用户不可见，"
            "接口层统一校验数据归属；敏感字段（证件、家庭、联系方式等）在服务端采用 AES-256-GCM "
            "字段级加密后落库，接口只返回打码后的结果，明文仅在「显示」单条查看与生成填写方案时按需解密；第三方平台账号凭据与登录态采用信封加密存储，"
            "每用户一把数据密钥并由服务端主密钥包裹，主密钥不入库、明文不落日志；"
            "简历文件存储于对象存储并通过预签名链接下载，不提供公开访问；"
            "AI 对话在发送与落库前自动脱敏；系统仅记录操作审计日志，不记录敏感明文。",
        ],
    ),
]


def _set_run(run, size_pt: float, bold: bool = False, color: RGBColor | None = None) -> None:
    run.font.name = "宋体"
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    rf = run._element.get_or_add_rPr().get_or_add_rFonts()
    rf.set(qn("w:ascii"), "宋体")
    rf.set(qn("w:hAnsi"), "宋体")
    rf.set(qn("w:eastAsia"), "宋体")


def build(out_path: str) -> None:
    doc = Document()

    sec = doc.sections[0]
    sec.page_width = Emu(7560310)
    sec.page_height = Emu(10692130)
    sec.top_margin = Emu(720090)
    sec.bottom_margin = Emu(720090)
    sec.left_margin = Emu(791845)
    sec.right_margin = Emu(791845)

    normal = doc.styles["Normal"]
    normal.font.name = "宋体"
    normal.font.size = Pt(11)
    rf = normal.element.get_or_add_rPr().get_or_add_rFonts()
    rf.set(qn("w:ascii"), "宋体")
    rf.set(qn("w:hAnsi"), "宋体")
    rf.set(qn("w:eastAsia"), "宋体")

    # 標題
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_run(p.add_run(TITLE), 20, bold=True)

    # 副標題
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_run(p.add_run(SUBTITLE), 16, bold=True)

    doc.add_paragraph("")

    for heading, bodies in SECTIONS:
        h = doc.add_heading(level=2)
        _set_run(h.add_run(heading), 13, bold=True, color=RGBColor(0x4F, 0x81, 0xBD))
        for body in bodies:
            bp = doc.add_paragraph()
            _set_run(bp.add_run(body), 11)

    doc.save(out_path)
    n = len(SECTIONS)
    print(f"sections={n} paragraphs={len(doc.paragraphs)}")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/Users/harryma/DeepSeekHarness/.tmp_resume/out/manual.docx"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    build(out)
