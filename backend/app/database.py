"""Database configuration and session management."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy import DateTime
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings

# Create async engine with connection pool settings.
#
# ``pool_pre_ping`` issues a cheap ``SELECT 1`` before checking out a
# connection so stale sockets (DB restart, NAT/firewall idle drop) are
# transparently recycled instead of failing the next request with a
# generic "connection lost". ``pool_recycle=3600`` ages connections out
# proactively so we don't accumulate idle ones a proxy might silently
# close.
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True,
    echo=settings.DB_ECHO,
)


class UnitOfWorkSession(AsyncSession):
    """Session that announces its events only once they are true.

    Handlers subscribe to facts, not intentions, and they read them
    through their own sessions. Publishing from inside an open
    transaction therefore announces something no other connection can
    see — audit finding S2. Publishers queue with
    ``event_bus.publish_after_commit(db, ...)``; this session drains the
    queue after the commit lands and drops it on rollback.

    In-process and non-durable: a crash between the commit and the
    dispatch loses the events. A durable outbox is the next step up, and
    it is a separate decision — this closes the correctness hole without
    a new table.
    """

    async def commit(self) -> None:
        await super().commit()

        # Import here: ``app.core.events`` is imported by every module,
        # and half of them import ``app.database``.
        from app.core.events import event_bus

        await event_bus.dispatch_pending(self)

    async def rollback(self) -> None:
        from app.core.events import event_bus

        event_bus.discard_pending(self)
        await super().rollback()


# ``expire_on_commit=False`` keeps ORM objects hydrated after a commit
# so the router can serialise the response without an extra refresh
# round-trip. Anything streaming or kept across awaits (long-lived
# tasks, websockets) must re-fetch explicitly — but the request-scoped
# pattern that dominates the codebase relies on this.
async_session_maker = async_sessionmaker(
    engine,
    class_=UnitOfWorkSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


class TimestampMixin:
    """Mixin that adds created_at and updated_at columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides a database session.

    Its exit runs **after the response has been sent** — a generator
    dependency defaults to FastAPI's ``"request"`` scope — so the commit
    here is only the fallback for work done while a response streams.
    Every endpoint's own work is committed earlier, by
    :func:`commit_before_response`.
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def commit_before_response(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AsyncGenerator[None, None]:
    """Commit the request's session before the client hears the result.

    Mounted app-wide with ``scope="function"``, whose exit runs as the
    endpoint returns — before the response is sent. Left to ``get_db``,
    a client was told ``201`` while the row was still uncommitted: an
    immediate read could miss it (the quick-create e2e did, on CI's slower
    disk), and a commit that failed afterwards reported success for data
    that was rolled back. Now that failure is the response.

    Same cached session as the endpoint's ``Depends(get_db)``; ``get_db``
    still opens and closes it at request scope, so a streaming response
    keeps its session while it streams. On an exception the ``yield``
    raises, nothing is committed, and ``get_db`` rolls back.
    """
    yield
    await db.commit()


async def init_db() -> None:
    """Initialize database tables. For development only."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
