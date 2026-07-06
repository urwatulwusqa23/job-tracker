from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

is_sqlite = settings.DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False} if is_sqlite else {}
# pool_pre_ping avoids "server closed the connection" errors on managed Postgres instances
# that recycle idle connections (e.g. free-tier Render/Railway Postgres).
engine_kwargs = {} if is_sqlite else {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 10}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, **engine_kwargs)

if is_sqlite:
    @event.listens_for(engine, "connect")
    def _enable_sqlite_fk(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
