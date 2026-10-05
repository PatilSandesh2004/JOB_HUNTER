from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from ai_service.app.core.config import settings

# SQLAlchemy declarative base for all ORM models.
Base = declarative_base()

# Async Engine setup using database URL from settings.
engine = create_async_engine(settings.database_url, echo=False, future=True)

# Async Session Factory for Dependency Injection in FastAPI endpoints.
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


# Dependency provider yielding an async SQLAlchemy session.
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
