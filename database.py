import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime
from typing import Optional
from sqlalchemy import Text, func
from config import DATABASE_URL

# إعداد المحرك - إعدادات ممتازة ومناسبة لقواعد البيانات السحابية (مثل Neon، Supabase، Render)
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
    # ✅ إضافة تمثيل أساسي لجميع الكائنات لتسهيل القراءة والتتبع
    def __repr__(self):
        return f"<{self.__class__.__name__} {', '.join([f'{c.name}={getattr(self, c.name)!r}' for c in self.__table__.columns])}>"


class UserConfig(Base):
    __tablename__ = "users_config"
    
    telegram_id: Mapped[int] = mapped_column(primary_key=True)
    paper_capital: Mapped[float] = mapped_column(default=100.0)
    is_active: Mapped[bool] = mapped_column(default=False) # للتحكم الكلي في النظام
    elite_enabled: Mapped[bool] = mapped_column(default=True) # مفتاح التحكم في إشارات النخبة
    risk_level: Mapped[str] = mapped_column(default="medium") # مستوى المخاطرة: low, medium, high


class TrackedCoin(Base):
    __tablename__ = "tracked_coins_v3"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(unique=True, nullable=False) # رمز العملة فريد ومطلوب
    timeframe: Mapped[str] = mapped_column(default="15m") # الإطار الزمني المحدد
    allocated_capital: Mapped[float] = mapped_column(default=50.0) # رأس المال المخصص
    # ✅ تعديل: استخدام func.now() لضمان دقة التوقيت على الخادم
    added_at: Mapped[datetime] = mapped_column(server_default=func.now()) 


class PaperTrade(Base):
    __tablename__ = "paper_trades_v3"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(nullable=False)
    type: Mapped[str] = mapped_column(nullable=False) # BUY / SELL
    entry_price: Mapped[float] = mapped_column(nullable=False)
    stop_loss: Mapped[Optional[float]] = mapped_column(nullable=True)
    take_profit: Mapped[Optional[float]] = mapped_column(nullable=True)
    exit_price: Mapped[Optional[float]] = mapped_column(nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    amount: Mapped[float] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(default="OPEN") # OPEN / WON / LOST / CANCELED

    # بيانات التحليل المتقدم والنخبة
    is_elite: Mapped[bool] = mapped_column(default=False) # هل الصفقة من فئة النخبة؟
    confidence: Mapped[float] = mapped_column(default=0.0) # نسبة الثقة 0-100%
    result_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # شرح نتيجة الصفقة
    technical_snapshot: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # بيانات المؤشرات وقت الدخول

    pnl: Mapped[float] = mapped_column(default=0.0) # الربح والخسارة
    # ✅ تعديل: توقيت دقيق ومطابق للخادم
    timestamp: Mapped[datetime] = mapped_column(server_default=func.now())


async def init_db():
    async with engine.begin() as conn:
        # تنشئ الجداول إذا لم تكن موجودة، ولن تحذف البيانات الموجودة
        await conn.run_sync(Base.metadata.create_all)
        print("✅ تم التحقق من بنية قاعدة البيانات وإنشاء الجداول المفقودة (إن وجدت).")
