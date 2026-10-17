# 3) 隊列按貼合度排序（同公司取最高分）
f = "app/services/apply_engine.py"
src = open(f, encoding="utf-8").read()
old = """              AND NOT EXISTS (
                SELECT 1 FROM applications a2
                JOIN job_postings p2 ON p2.id = a2.posting_id
                WHERE a2.user_id = :uid AND p2.company_name = p.company_name
                  AND a2.status NOT IN ('aborted', 'duplicate_skip', 'not_supported')
              )
            ON CONFLICT (user_id, posting_id) DO NOTHING"""
new = """              AND NOT EXISTS (
                SELECT 1 FROM applications a2
                JOIN job_postings p2 ON p2.id = a2.posting_id
                WHERE a2.user_id = :uid AND p2.company_name = p.company_name
                  AND a2.status NOT IN ('aborted', 'duplicate_skip', 'not_supported')
              )
            ORDER BY m.match_score DESC NULLS LAST
            ON CONFLICT (user_id, posting_id) DO NOTHING"""
assert old in src, "apply_engine anchor not found"
src = src.replace(old, new)
open(f, "w", encoding="utf-8").write(src)
print("queue ordering done")

# 4) companies 列表按 careers_url 去重
f = "app/api/companies.py"
src = open(f, encoding="utf-8").read()
old = '''    rows = db.execute(
        text(
            "SELECT id, company_name, aliases, careers_url, platform, notes, is_active, created_at "
            "FROM watched_companies WHERE user_id = :uid ORDER BY created_at DESC"
        ),
        {"uid": user["id"]},
    ).mappings().all()'''
new = '''    rows = db.execute(
        text(
            """
            SELECT DISTINCT ON (COALESCE(careers_url, company_name)) id, company_name, aliases,
                   careers_url, platform, notes, is_active, created_at
            FROM watched_companies WHERE user_id = :uid
            ORDER BY COALESCE(careers_url, company_name), created_at
            """
        ),
        {"uid": user["id"]},
    ).mappings().all()'''
assert old in src, "companies anchor not found"
src = src.replace(old, new)
open(f, "w", encoding="utf-8").write(src)
print("companies dedupe done")
