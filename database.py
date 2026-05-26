import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime
from typing import Optional
from config import DATABASE_URL

# إعداد المحرك
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
    __tablename__ = "users_config"
    telegram_id: Mapped[int] = mapped_column(primary_key=True)
    paper_capital: Mapped[float] = mapped_column(default=100.0)
    is_active: Mapped[bool] = mapped_column(default=False)
    risk_level: Mapped[str] = mapped_column(default="medium")

class TrackedCoin(Base):
    __tablename__ = "tracked_coins_v3"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(unique=True)
    timeframe: Mapped[str] = mapped_column(default="15m")
    allocated_capital: Mapped[float] = mapped_column(default=50.0)
    added_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

class PaperTrade(Base):
    __tablename__ = "paper_trades_v2"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column()
    type: Mapped[str] = mapped_column() # BUY or SELL
    entry_price: Mapped[float] = mapped_column()
    # إضافة الأعمدة التي كانت تسبب خطأ 'invalid keyword argument'
    stop_loss: Mapped[Optional[float]] = mapped_column(nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(nullable=True)
    exit_price: Mapped[Optional[float]] = mapped_column(nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    amount: Mapped[float] = mapped_column()
    status: Mapped[str] = mapped_column(default="OPEN")
    pnl: Mapped[float] = mapped_column(default=0.0)
    timestamp: Mapped[datetime] = mapped_column(default=datetime.utcnow)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
