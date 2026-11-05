"""投遞適配器框架：數據結構與協議。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ApplyContext:
    """Worker 傳給適配器的完整上下文。"""
    user_id: str
    application_id: str
    posting: dict                # job_postings 行（company_name/title/apply_url/description_text…）
    payload: dict                # build_candidate_payload 結果（含 resume_file 等）
    resume_text: str             # 簡歷 markdown 全文
    cover_letter: str | None     # Cover Letter 文本（可能為 None）
    resume_local_path: str | None  # 已下載到本地的簡歷文件路徑
    settings: dict               # user_settings 行
    dry_run: bool = False
    account: dict | None = None  # 平台帳號明文 {'login':…, 'password':…}（已解密的登錄憑據）


@dataclass
class ManualRequest:
    """需要人工介入的請求（驗證碼/登錄/缺字段/缺附件）。"""
    task_type: str               # captcha | login_required | missing_field | missing_file | confirm_content | other
    question: str                # 給用戶看的中文描述（FR-3c 直接框）
    options: dict | None = None  # H5 表單 schema：{字段: {label, type}}
    screenshot_path: str | None = None


@dataclass
class ApplyResult:
    success: bool
    external_ref: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    screenshots: list[str] = field(default_factory=list)
    manual: ManualRequest | None = None


class BaseApplyAdapter(Protocol):
    name: str

    def apply(self, ctx: ApplyContext) -> ApplyResult: ...


_APPLY_REGISTRY: dict[str, BaseApplyAdapter] = {}


def register_adapter(adapter: BaseApplyAdapter) -> BaseApplyAdapter:
    _APPLY_REGISTRY[adapter.name] = adapter
    return adapter


def get_apply_adapter(source: str) -> BaseApplyAdapter:
    """投遞適配器註冊表；未知來源降級通用適配器。"""
    entry = _APPLY_REGISTRY.get(source)
    if entry is None:
        entry = _APPLY_REGISTRY["generic"]
    if isinstance(entry, type):
        entry = entry()
        if source in _APPLY_REGISTRY:
            _APPLY_REGISTRY[source] = entry
    return entry
