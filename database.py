import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime
from typing import Optional
from sqlalchemy import Text
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
    # مفتاح التحكم في إشعارات النخبة (ON/OFF)
    elite_enabled: Mapped[bool] = mapped_column(default=True)
    risk_level: Mapped[str] = mapped_column(default="medium")

class TrackedCoin(Base):
    __tablename__ = "tracked_coins_v3"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(unique=True)
    timeframe: Mapped[str] = mapped_column(default="15m")
    allocated_capital: Mapped[float] = mapped_column(default=50.0)
    added_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

class PaperTrade(Base):
    __tablename__ = "paper_trades_v3" # تم تحديث الإصدار لضمان تطبيق التعديلات الجديدة
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column()
    type: Mapped[str] = mapped_column() # BUY or SELL
    entry_price: Mapped[float] = mapped_column()
    stop_loss: Mapped[Optional[float]] = mapped_column(nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(nullable=True)
    exit_price: Mapped[Optional[float]] = mapped_column(nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    amount: Mapped[float] = mapped_column()
    status: Mapped[str] = mapped_column(default="OPEN") # OPEN, WON, LOST
    
    # --- أعمدة النخبة والتحليل الجديدة ---
    is_elite: Mapped[bool] = mapped_column(default=False) # هل هي صفقة نخبة أم تدريب مخفي؟
    confidence: Mapped[float] = mapped_column(default=0.0) # نسبة الثقة وقت الدخول
    result_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # تقرير سبب النجاح أو الفشل
    technical_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # حالة المؤشرات وقت الدخول (RSI, MACD, etc.)
    
    pnl: Mapped[float] = mapped_column(default=0.0)
    timestamp: Mapped[datetime] = mapped_column(default=datetime.utcnow)

async def init_db():
    async with engine.begin() as conn:
        # ملاحظة: سيقوم هذا بإنشاء جداول جديدة. إذا كان الجدول موجوداً مسبقاً، قد تحتاج لحذفه أو استخدام Alembic.
        await conn.run_sync(Base.metadata.create_all)
