# 5) 清理生產：重複關注公司 + 每公司只保留最高貼合度投遞
from sqlalchemy import text

from app.db import SessionLocal

UID = "b2b614f6-6867-467e-bbdd-d3eb453f3353"
db = SessionLocal()
db.execute(text("""
DELETE FROM watched_companies w WHERE user_id=:u
AND id NOT IN (SELECT MIN(id) FROM watched_companies
  WHERE user_id=:u GROUP BY COALESCE(careers_url, company_name))
"""), {"u": UID})
db.execute(text("""
UPDATE applications SET status='aborted', status_reason='按貼合度只保留最高分崗位', updated_at=now()
WHERE user_id=:u
AND status IN ('queued','needs_input','in_progress')
AND id NOT IN (
  SELECT a.id FROM applications a
  JOIN job_postings p ON p.id=a.posting_id
  JOIN job_matches m ON m.id=a.match_id
  WHERE a.user_id=:u
  AND a.status IN ('queued','needs_input','in_progress')
  AND a.id = (
    SELECT a2.id FROM applications a2
    JOIN job_postings p2 ON p2.id=a2.posting_id
    JOIN job_matches m2 ON m2.id=a2.match_id
    WHERE a2.user_id=:u
    AND a2.status IN ('queued','needs_input','in_progress')
    AND p2.company_name = p.company_name
    ORDER BY m2.match_score DESC NULLS LAST LIMIT 1
  )
)"""), {"u": UID})
db.execute(text("""
UPDATE manual_tasks SET status='cancelled'
WHERE user_id=:u AND status='open'
AND application_id IN (
  SELECT id FROM applications WHERE user_id=:u AND status='aborted'
)"""), {"u": UID})
db.commit()
rows = db.execute(text("""
SELECT p.company_name, p.title, a.status, m.match_score FROM applications a
JOIN job_postings p ON p.id=a.posting_id
LEFT JOIN job_matches m ON m.id=a.match_id
WHERE a.user_id=:u AND a.status IN ('queued','needs_input','in_progress','submitted')
"""), {"u": UID}).all()
print("保留的投遞:")
for r in rows:
    print(" ", r[0][:24], "|", r[1][:26], "->", r[2], "|", r[3])
n = db.execute(text("SELECT COUNT(*) FROM manual_tasks WHERE user_id=:u AND status='open'"),
               {"u": UID}).scalar()
print("待處理任務:", n)
db.close()
