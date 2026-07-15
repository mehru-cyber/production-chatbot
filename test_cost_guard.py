from app.db.session import SessionLocal
from app.middleware.cost_guard import reserve_usage_or_raise
import uuid

db = SessionLocal()
try:
    fake_user_id = uuid.uuid4()
    result = reserve_usage_or_raise(db, fake_user_id)
    print("Reserved:", result)
finally:
    db.close()