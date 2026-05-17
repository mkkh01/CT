from datetime import datetime
from sqlalchemy.orm import Session
from database import ShadowTrade, StrategyStat
from logger import setup_logger

logger = setup_logger("ShadowLearningEngine")

class ShadowLearningEngine:
    @staticmethod
    def open_shadow_trade(db: Session, setup: dict, regime_data: dict) -> bool:
        """
        تسجيل وفتح صفقة ظل افتراضية جديدة في قاعدة البيانات للمراقبة والتعلم الإحصائي.
        """
        try:
            new_trade = ShadowTrade(
                symbol=setup['symbol'],
                strategy=setup['name'],
                entry=float(setup['entry']),
                sl=float(setup['sl']),
                tp=float(setup['tp']),
                result="PENDING",
                pnl=0.0,
                regime=regime_data['regime'],
                session="ALPHA_SHADOW",
                diagnostics={"initial_rsi": regime_data.get("rsi"), "volatility": regime_data.get("volatility")},
                created_at=datetime.utcnow()
            )
            db.add(new_trade)
            db.commit()
            logger.info(f"🚀 [صفقات الظل] تم فتح صفقة ظل افتراضية ناجحة للعملة {setup['symbol']} عبر استراتيجية {setup['name']}.")
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"خطأ أثناء فتح صفقة الظل في قاعدة البيانات: {str(e)}")
            return False

    @classmethod
    def update_live_shadow_trades(cls, db: Session, current_prices: dict):
        """
        تحديث صفقات الظل المفتوحة حياً ومقارنة السعر الحالي بأوامر جني الأرباح (TP) ووقف الخسارة (SL).
        ملاحظة: current_prices هو قاموس يحتوي على العملة وسعرها اللحظي الحالي مثل: {"BTC/USDT": 64500.0}
        """
        try:
            # جلب كافة صفقات الظل المعلقة (PENDING) من قاعدة بيانات Render
            active_trades = db.query(ShadowTrade).filter(ShadowTrade.result == "PENDING").all()
            
            for trade in active_trades:
                symbol = trade.symbol
                if symbol not in current_prices:
                    continue
                    
                current_price = float(current_prices[symbol])
                is_closed = False
                result = "PENDING"
                pnl = 0.0
                
                # فحص شروط الإغلاق لصفقات الشراء (Long Trades)
                if trade.sl < trade.tp:  
                    if current_price >= trade.tp:
                        result = "WIN"
                        pnl = (trade.tp - trade.entry) / trade.entry
                        is_closed = True
                    elif current_price <= trade.sl:
                        result = "LOSS"
                        pnl = (trade.sl - trade.entry) / trade.entry
                        is_closed = True
                        
                # فحص شروط الإغلاق لصفقات البيع (Short Trades)
                else:
                    if current_price <= trade.tp:
                        result = "WIN"
                        pnl = (trade.entry - trade.tp) / trade.entry
                        is_closed = True
                    elif current_price >= trade.sl:
                        result = "LOSS"
                        pnl = (trade.entry - trade.sl) / trade.entry
                        is_closed = True

                # إذا ضرب السعر الهدف أو الوقف، يتم تحديث السجل الإحصائي فوراً
                if is_closed:
                    trade.result = result
                    trade.pnl = pnl * 100  # حفظ النسبة المئوية للربح أو الخسارة
                    trade.closed_at = datetime.utcnow()
                    
                    # تحديث التشخيص النهائي لتعلم الخوارزمية
                    trade.diagnostics = {
                        "end_price": current_price,
                        "execution_type": "AUTOMATIC_HIT"
                    }
                    
                    # استدعاء دالة تحديث الإحصائيات التراكمية للاستراتيجية
                    cls._update_strategy_statistics(db, trade.strategy, result, trade.entry, trade.sl, trade.tp)
                    
                    logger.info(f"🎯 [صفقات الظل] إغلاق صفقة ظل على {symbol}. النتيجة: {result} | العائد: {trade.pnl:.2f}%")
                    
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"خطأ غير متوقع أثناء تحديث صفقات الظل الحية: {str(e)}")

    @staticmethod
    def _update_strategy_statistics(db: Session, strategy_name: str, result: str, entry: float, sl: float, tp: float):
        """
        دالة داخلية لتحديث جدول إحصائيات الاستراتيجيات (StrategyStats) تراكمياً في قاعدة البيانات.
        """
        try:
            stat = db.query(StrategyStat).filter(StrategyStat.strategy_name == strategy_name).first()
            
            # إذا لم تكن الاستراتيجية مسجلة من قبل، يتم إنشاؤها فوراً
            if not stat:
                stat = StrategyStat(strategy_name=strategy_name, total_trades=0, wins=0, losses=0, avg_rr=0.0, profit_factor=1.0)
                db.add(stat)
                
            stat.total_trades += 1
            if result == "WIN":
                stat.wins += 1
            elif result == "LOSS":
                stat.losses += 1
                
            # حساب معدل العائد مقابل المخاطرة (Risk-to-Reward Ratio) الفعلي المحقق هندسياً
            current_rr = abs(tp - entry) / abs(entry - sl) if abs(entry - sl) > 0 else 1.0
            stat.avg_rr = ((stat.avg_rr * (stat.total_trades - 1)) + current_rr) / stat.total_trades
            
            # تحديث معامل الربحية التراكمي (Profit Factor) تقريبياً
            total_losses_count = max(1, stat.losses)
            stat.profit_factor = float(stat.wins / total_losses_count) * stat.avg_rr
            stat.updated_at = datetime.utcnow()
            
        except Exception as e:
            logger.error(f"فشل تحديث الجدول الإحصائي للاستراتيجية {strategy_name}: {str(e)}")
