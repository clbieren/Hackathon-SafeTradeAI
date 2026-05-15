from typing import List, Dict, Tuple, Optional, Union, Any
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

# ---------------------------------------------------------------------------
# Async Engine
# ---------------------------------------------------------------------------
# pool_pre_ping: bağlantı havuzundaki ölü bağlantıları otomatik temizler.
# echo: SQL sorgularını konsola yazdırır (sadece debug modunda).
engine_kwargs = {
    "pool_pre_ping": True,
    "echo": settings.debug,
}

if settings.database_url.startswith("postgresql"):
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20

engine = create_async_engine(
    settings.database_url,
    **engine_kwargs
)
# ---------------------------------------------------------------------------
# Session Factory
# ---------------------------------------------------------------------------
# expire_on_commit=False: commit sonrası nesnelere erişimde ekstra sorgu engellenir.
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ---------------------------------------------------------------------------
# Base Class
# ---------------------------------------------------------------------------
class Base(DeclarativeBase):
    """Tüm ORM modellerinin kalıtım aldığı temel sınıf."""
    pass


# ---------------------------------------------------------------------------
# FastAPI Dependency: DB Session
# ---------------------------------------------------------------------------
async def get_db() -> AsyncSession:  # type: ignore[return]
    """
    Her HTTP isteği için yeni bir veritabanı oturumu açar.
    İstek tamamlandığında (başarılı veya hatalı) oturumu kapatır.

    Kullanım:
        @app.get("/example")
        async def example(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
