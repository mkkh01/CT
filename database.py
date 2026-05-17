import json
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, JSON
from sqlalchemy.orm import declarative_base, sessionmaker
from config import Config

# 1. إنشاء محرك الاتصال بقاعدة البيانات المباشرة الحقيقية
# تم تفعيل pool_pre_ping لضمان فحص الاتصال التلقائي وإعادة الاتصال في حال انقطاعه على سيرفرات Render
engine = create_engine(
    Config.DATABASE_URL, 
    pool_pre_ping=True,
    pool_recycle=3600
)

# 2. إنشاء جلسة التعامل مع البيانات (Session Factory)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# القائمة الأساسية لبناء الجداول البرمجية (ORM Model Base)
Base = declarative_base()

# ------------------------------------------------------------------
# [1] جدول المستخدمين وإعدادات رأس المال والمخاطر (users)
# ------------------------------------------------------------------
class User(Base):
    __tablename__ = 'users'
    user_id = Column(Integer, primary_key=True)
    capital = Column(Float, default=1000.0)              # رأس المال الافتراضي لحساب أحجام الصفقات
    risk_level = Column(String, default="CONSERVATIVE")  # مستويات المخاطرة: CONSERVATIVE, MODERATE, AGGRESSIVE
    created_at = Column(DateTime, default=datetime.utcnow)

# ------------------------------------------------------------------
# [2] جدول قائمة المراقبة النشطة للعملات (watchlist)
# ------------------------------------------------------------------
class Watchlist(Base):
    __tablename__ = 'watchlist'
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, unique=True, nullable=False) # مثل: BTC/USDT
    enabled = Column(Boolean, default=True)              # لتفعيل أو تعطيل فحص العملة مؤقتاً
    added_at = Column(DateTime, default=datetime.utcnow)

# ------------------------------------------------------------------
# [3] جدول سجل الإشارات الفعلي المرسل على التلغرام (signals)
# ------------------------------------------------------------------
class Signal(Base):
    __tablename__ = 'signals'
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    direction = Column(String, nullable=False)           # BUY, SELL
    entry = Column(Float, nullable=False)
    sl = Column(Float, nullable=False)                   # Stop Loss
    tp = Column(Float, nullable=False)                   # Take Profit
    confidence = Column(Float, nullable=False)           # معدل الثقة (0 - 100)
    strategy = Column(String, nullable=False)            # اسم الاستراتيجية المستخدمة
    regime = Column(String, nullable=False)              # حالة السوق أثناء صدور الإشارة
    result = Column(String, default="PENDING")           # النتيجة: WIN, LOSS, TIMEOUT, PENDING
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

# ------------------------------------------------------------------
# [4] جدول صفقات الظل الافتراضية للتعلم الإحصائي (shadow_trades)
# ------------------------------------------------------------------
class ShadowTrade(Base):
    __tablename__ = 'shadow_trades'
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    strategy = Column(String, nullable=False)
    entry = Column(Float, nullable=False)
    sl = Column(Float, nullable=False)
    tp = Column(Float, nullable=False)
    result = Column(String, default="PENDING")
    pnl = Column(Float, default=0.0)                     # الربح أو الخسارة الافتراضية
    regime = Column(String, nullable=False)
    session = Column(String, default="ALPHA_SHADOW")
    diagnostics = Column(JSON, nullable=True)            # تفاصيل أسباب الفشل أو النجاح بصيغة JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime, nullable=True)

# ------------------------------------------------------------------
# [5] جدول الإحصائيات التراكمية لكل استراتيجية (strategy_stats)
# ------------------------------------------------------------------
class StrategyStat(Base):
    __tablename__ = 'strategy_stats'
    strategy_name = Column(String, primary_key=True)     # اسم الاستراتيجية كمفتاح أساسي
    total_trades = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    avg_rr = Column(Float, default=0.0)                  # متوسط عائد المخاطرة المحقق فعلياً
    profit_factor = Column(Float, default=1.0)           # عامل الربحية الإحصائي
    updated_at = Column(DateTime, default=datetime.utcnow)

# ------------------------------------------------------------------
# [6] سجلات بيئة وحالة السوق العامة (market_logs)
# ------------------------------------------------------------------
class MarketLog(Base):
    __tablename__ = 'market_logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    market_regime = Column(String, nullable=False)       # TRENDING, RANGING, CHOPPY, PANIC
    volatility = Column(Float, nullable=False)           # نسبة التقلب الحالية
    btc_dominance = Column(Float, nullable=False)        # استحواذ البيتكوين
    sentiment_score = Column(Float, nullable=False)      # مؤشر المشاعر العام
    timestamp = Column(DateTime, default=datetime.utcnow)

# ------------------------------------------------------------------
# دالة الإنشاء التلقائي للجداول وبذر البيانات الأولية (init_db)
# ------------------------------------------------------------------
def init_db():
    # إنشاء الجداول في قاعدة بيانات Render الفريضة في حال لم تكن موجودة
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        # 1. بذر قائمة العملات الافتراضية لبدء الفحص التلقائي فورا
        if db.query(Watchlist).count() == 0:
            for sym in Config.DEFAULT_WATCHLIST:
                db.add(Watchlist(symbol=sym, enabled=True))
            db.commit()
            
        # 2. إدخال سجل حسابك كمسؤول (ADMIN_ID) تلقائياً بالإعدادات المحافظة
        if db.query(User).filter(User.user_id == Config.ADMIN_ID).count() == 0:
            db.add(User(user_id=Config.ADMIN_ID, capital=1000.0, risk_level="CONSERVATIVE"))
            db.commit()
    except Exception as e:
        print(f"⚠️ تنبيه أثناء تهيئة البيانات الأولية: {e}")
        db.rollback()
    finally:
        db.close()
