# database.py
import asyncio
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from config import DATABASE_URL

Base = declarative_base()

# --- الجداول (Models) ---
class UserConfig(Base):
    __tablename__ = 'users_config'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    paper_capital = Column(Float, default=1000.0)
    is_active = Column(Boolean, default=True)

class Watchlist(Base):
    __tablename__ = 'watchlists'
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), unique=True, nullable=False)

class PaperTrade(Base):
    __tablename__ = 'paper_trades'
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False) # BUY/SELL
    entry_price = Column(Float, nullable=False)
    position_size = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    status = Column(String(20), default="OPEN") # OPEN, WIN, LOSS
    opened_at = Column(DateTime, default=datetime.utcnow)

# --- محرك الاتصال (Engine) ---
engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    """إنشاء الجداول في قاعدة بيانات Render"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ تم الاتصال بقاعدة البيانات بنجاح.")
