import os
from collections.abc import AsyncGenerator

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base

load_dotenv()

DATABASE_URL: str | None = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("Database URL is not set")

engine = create_async_engine(DATABASE_URL, echo=False, future=True)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an :class:`AsyncSession` per request."""
    async with AsyncSessionLocal() as session:
        yield session


async def create_tables() -> None:
    """Create all tables that do not yet exist.  Call once at startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
