"""投遞引擎離線單測（無需網絡/數據庫）。"""
from types import SimpleNamespace

from app.apply.base import get_apply_adapter
from app.apply.generic_apply import _split_name, _value_for
from app.apply.greenhouse_apply import _split_name as _gh_split
from app.services.form_mapping import missing_fields


def test_missing_fields():
    assert missing_fields({}) == {
        "critical": ["full_name", "email", "phone"],
        "important": ["location", "visa_status", "resume_file", "education_entry"],
    }
    full = {
        "full_name": "張三", "email": "a@b.com", "phone": "138",
        "location": "HK", "visa_status": "PR", "resume_file": {"name": "r.pdf"},
        "education_entry": {"school": "X"},
    }
    assert missing_fields(full) == {"critical": [], "important": []}


def test_split_names():
    assert _gh_split("Harry Ma") == ("Harry", "Ma")
    assert _gh_split("Harry") == ("Harry", ".")
    assert _split_name("王 小明") == ("王", "小明")
    assert _split_name("") == ("Candidate", ".")


def test_value_for_mapping():
    ctx = SimpleNamespace(cover_letter="親愛的HR")
    payload = {"full_name": "Harry Ma", "email": "h@m.com", "phone": "123",
               "salary_expectation": "30k", "location": "HK"}
    v, matched = _value_for({"name": "email", "placeholder": "", "label": "Email"},
                            payload, ctx)
    assert v == "h@m.com" and matched
    v, matched = _value_for({"name": "cover_letter", "placeholder": "", "label": ""},
                            payload, ctx)
    assert v == "親愛的HR" and matched
    v, matched = _value_for({"name": "random_field", "placeholder": "", "label": ""},
                            payload, ctx)
    assert v == "" and not matched
    v, matched = _value_for({"name": "first_name", "placeholder": "", "label": ""},
                            payload, ctx)
    assert v == "Harry" and matched


def test_adapter_registry_fallback():
    assert get_apply_adapter("greenhouse").name == "greenhouse"
    assert get_apply_adapter("lever").name == "lever"
    assert get_apply_adapter("workday").name == "generic"      # 未知來源降級通用適配器
    assert get_apply_adapter("something_else").name == "generic"
