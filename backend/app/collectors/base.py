"""崗位採集適配器框架（FR-3a2）。

每個招聘來源實現一個 Collector；新增平台只需註冊一個新類，
投遞/匹配/推送流水線完全無感（開閉原則）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class JobPosting:
    source: str                      # 採集渠道標識（greenhouse/lever/workday/official）
    external_id: str                 # 平台側崗位 ID（與 source 組成去重鍵）
    company_name: str
    title: str
    apply_url: str | None = None
    location: str | None = None
    department: str | None = None
    description_text: str | None = None
    salary_range: dict | None = None
    posted_at: str | None = None     # ISO 字符串
    raw: dict = field(default_factory=dict)


class BaseCollector(Protocol):
    """收集器接口：給定一個目標（careers_url 或公司名），返回崗位列表。"""

    name: str

    def collect(self, target: dict) -> list[JobPosting]:
        """target: {'company_name': str, 'careers_url': str|None, 'platform': str}"""
        ...


_REGISTRY: dict[str, BaseCollector] = {}


def register(collector: BaseCollector) -> BaseCollector:
    _REGISTRY[collector.name] = collector
    return collector


def get_collector(name: str) -> BaseCollector:
    if name not in _REGISTRY:
        raise KeyError(f"未註冊的採集器: {name}（可用: {sorted(_REGISTRY)}）")
    return _REGISTRY[name]
