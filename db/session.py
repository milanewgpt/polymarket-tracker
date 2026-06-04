from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.models import Base


class DatabaseManager:
    def __init__(self, database_url: str) -> None:
        db_path = database_url.replace("sqlite+aiosqlite:///", "")
        if db_path and not db_path.startswith(":"):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_async_engine(database_url, echo=False)
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init_db(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # migrate: add started_at if it doesn't exist yet
            try:
                await conn.execute(
                    __import__("sqlalchemy").text(
                        "ALTER TABLE events ADD COLUMN started_at DATETIME"
                    )
                )
            except Exception:
                pass

    def get_session(self) -> AsyncSession:
        return self.session_factory()

    async def close(self) -> None:
        await self.engine.dispose()
