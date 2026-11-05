"""投遞適配器包：導入即註冊。

精簡版只保留一個通用投遞器（generic）：
所有招聘官網走同一套通用表單填充，無法確認提交結果時一律轉人工確認任務，
不再按平台維護定制投遞腳本。
"""
from app.apply import generic_apply  # noqa: F401
