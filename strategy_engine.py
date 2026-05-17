from logger import setup_logger

logger = setup_logger("StrategyEngine")

class StrategyEngine:
    
    @staticmethod
    def evaluate_trend_continuation(mtf_data: dict, regime_data: dict) -> dict:
        """
        الاستراتيجية 1: استمرار الاتجاه الاندفاعي (Trend Continuation)
        تعمل فقط في بيئات الاتجاهات الصريحة، وتستغل الارتدادات الصحية نحو المتوسطات.
        """
        # الحماية الهيكلية: ترفض العمل تماماً خارج بيئة الاتجاه الصريح
        if "TRENDING" not in regime_data['regime']:
            return {"decision": "NO_TRADE"}
            
        c_5m = mtf_data['5m']['close']
        atr_5m = mtf_data['5m']['atr']
        rsi_15m = mtf_data['15m']['rsi']
        c_1h = mtf_data['1h']['close']
        ema_1h = mtf_data['1h']['ema_20']
        
        # حالة الاتجاه الصاعد: السعر فوق متوسط الساعة، وهناك تصحيح صحي مؤقت على الـ 15 دقيقة
        if regime_data['regime'] == "TRENDING_BULLISH" and c_1h > ema_1h:
            if 40.0 <= rsi_15m <= 52.0:  
                entry = c_5m
                sl = entry - (2.0 * atr_5m)  # وقف خسارة ديناميكي يعتمد على التقلب
                tp = entry + (3.5 * atr_5m)  # هدف جني أرباح طموح متوافق مع الاتجاه
                rr = (tp - entry) / (entry - sl) if (entry - sl) > 0 else 0.0
                
                return {
                    "decision": "BUY", "entry": entry, "sl": sl, "tp": tp, "rr": rr,
                    "confidence_boost": 35.0, "name": "Trend_Continuation"
                }
                
        # حالة الاتجاه الهابط
        elif regime_data['regime'] == "TRENDING_BEARISH" and c_1h < ema_1h:
            if 48.0 <= rsi_15m <= 60.0:  
                entry = c_5m
                sl = entry + (2.0 * atr_5m)
                tp = entry - (3.5 * atr_5m)
                rr = (sl - entry) / (entry - tp) if (entry - tp) > 0 else 0.0
                
                return {
                    "decision": "SELL", "entry": entry, "sl": sl, "tp": tp, "rr": rr,
                    "confidence_boost": 35.0, "name": "Trend_Continuation"
                }
                
        return {"decision": "NO_TRADE"}

    @staticmethod
    def evaluate_breakout(mtf_data: dict, regime_data: dict) -> dict:
        """
        الاستراتيجية 2: الاختراقات الحجمية الهيكلية (Breakout Strategy)
        تستهدف ركوب الموجة فور انفجار السعر خارج النطاقات الضيقة مدعوماً بزخم حاد.
        """
        # حظر التداول في البيئات العشوائية والانهيارية لمنع الاختراقات الكاذبة (False Breakouts)
        if regime_data['regime'] in ["CHOPPY", "PANIC"]:
            return {"decision": "NO_TRADE"}
            
        c_5m = mtf_data['5m']['close']
        atr_5m = mtf_data['5m']['atr']
        rsi_5m = mtf_data['5m']['rsi']
        macd_5m = mtf_data['5m']['macd']
        macd_sig_5m = mtf_data['5m']['macd_sig']
        
        # اختراق صاعد: RSI يعكس نية انفجارية والماكد يتقاطع إيجابياً فوق خط الإشارة
        if rsi_5m > 62.0 and macd_5m > macd_sig_5m:
            entry = c_5m
            sl = entry - (1.5 * atr_5m)  # وقف خسارة أقرب نظراً لطبيعة الاختراق السريعة
            tp = entry + (3.0 * atr_5m)
            rr = (tp - entry) / (entry - sl) if (entry - sl) > 0 else 0.0
            
            return {
                "decision": "BUY", "entry": entry, "sl": sl, "tp": tp, "rr": rr,
                "confidence_boost": 30.0, "name": "Breakout_Strategy"
            }
            
        # اختراق هابط
        elif rsi_5m < 38.0 and macd_5m < macd_sig_5m:
            entry = c_5m
            sl = entry + (1.5 * atr_5m)
            tp = entry - (3.0 * atr_5m)
            rr = (sl - entry) / (entry - tp) if (entry - tp) > 0 else 0.0
            
            return {
                "decision": "SELL", "entry": entry, "sl": sl, "tp": tp, "rr": rr,
                "confidence_boost": 30.0, "name": "Breakout_Strategy"
            }
            
        return {"decision": "NO_TRADE"}

    @staticmethod
    def evaluate_range_reversal(mtf_data: dict, regime_data: dict) -> dict:
        """
        الاستراتيجية 3: الارتداد من قيعان وقمم النطاقات العرضية (Range Reversal)
        تستغل تذبذب السعر المنظم داخل قنوات أفقية واضحة للبيع من القمم والشراء من القيعان.
        """
        # تعمل فقط وحصراً عندما يكون السوق في حالة تذبذب عرضي مستقر ومثالي
        if regime_data['regime'] != "RANGING":
            return {"decision": "NO_TRADE"}
            
        c_5m = mtf_data['5m']['close']
        atr_5m = mtf_data['5m']['atr']
        rsi_15m = mtf_data['15m']['rsi']
        
        # الشراء من قاع النطاق العرضي عند ذروة البيع اللحظية
        if rsi_15m <= 32.0:
            entry = c_5m
            sl = entry - (1.2 * atr_5m)  # وقف ضيق جداً لأن كسر النطاق يلغي الفكرة فوراً
            tp = entry + (2.5 * atr_5m)
            rr = (tp - entry) / (entry - sl) if (entry - sl) > 0 else 0.0
            
            return {
                "decision": "BUY", "entry": entry, "sl": sl, "tp": tp, "rr": rr,
                "confidence_boost": 40.0, "name": "Range_Reversal"
            }
            
        # البيع من قمة النطاق العرضي عند ذروة الشراء اللحظية
        elif rsi_15m >= 68.0:
            entry = c_5m
            sl = entry + (1.2 * atr_5m)
            tp = entry - (2.5 * atr_5m)
            rr = (sl - entry) / (entry - tp) if (entry - tp) > 0 else 0.0
            
            return {
                "decision": "SELL", "entry": entry, "sl": sl, "tp": tp, "rr": rr,
                "confidence_boost": 40.0, "name": "Range_Reversal"
            }
            
        return {"decision": "NO_TRADE"}
