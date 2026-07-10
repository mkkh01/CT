from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime
from typing import Optional
from sqlalchemy import Text, func, JSON
from config.settings import DATABASE_URL

# Institutional Database Schema for CT V4.0
engine = create_async_engine(
    DATABASE_URL,
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0
    }
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

class Base(DeclarativeBase):
    pass

class UserConfig(Base):
    __tablename__ = "user_config_v4"
    telegram_id: Mapped[int] = mapped_column(primary_key=True)
    total_capital: Mapped[float] = mapped_column(default=1000.0)
    is_active: Mapped[bool] = mapped_column(default=False)
    emergency_stop: Mapped[bool] = mapped_column(default=False)
    risk_per_trade: Mapped[float] = mapped_column(default=1.0)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
