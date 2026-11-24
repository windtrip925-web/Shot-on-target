from sqlalchemy import create_engine, text
from .config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)

def query(sql: str, **params) -> list[dict]:
    with engine.begin() as c:
        r = c.execute(text(sql), params)
        return [dict(x._mapping) for x in r] if r.returns_rows else []

def execute(sql: str, **params) -> int:
    with engine.begin() as c:
        return c.execute(text(sql), params).rowcount
