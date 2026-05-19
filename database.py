import asyncio
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from config import DATABASE_URL

Base = declarative_base()

class UserConfig(Base):
    __tablename__ = 'users_config'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    paper_capital = Column(Float, default=1000.0)
    is_active = Column(Boolean, default=True)

class TrackedCoin(Base):
    __tablename__ = 'tracked_coins_v3' # نسخة جديدة لتجنب تعارض الجداول
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), unique=True, nullable=False)
    timeframe = Column(String(10), default="15m")
    allocated_capital = Column(Float, default=100.0)

class PaperTrade(Base):
    __tablename__ = 'paper_trades_v2' # نسخة جديدة لدعم التتبع
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    entry_price = Column(Float, nullable=False)
    position_size = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    is_visible = Column(Boolean, default=True) # هل الصفقة ظهرت للمستخدم أم كانت تدريبية خفية
    status = Column(String(20), default="OPEN") # OPEN, WON, LOST
    exit_price = Column(Float, nullable=True)
    analysis = Column(Text, nullable=True) # تحليل سبب النجاح أو الفشل
    opened_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ تم تحديث قاعدة البيانات لدعم نظام التعلم والمراقبة.")
