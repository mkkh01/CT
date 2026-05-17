from logger import setup_logger

logger = setup_logger("ScoringEngine")

class ScoringEngine:
    @staticmethod
    def calculate_score(setup: dict, regime_data: dict, mtf_data: dict) -> float:
        """
        حساب معامل الثقة الإحصائي للصفقة بناءً على توافق المؤشرات والبيئة العامة.
        المخرجات: درجة رقمية تتراوح بين 0.0 و 100.0
        """
        try:
            # نقطة البداية الأساسية لأي صفقة ناجية من الفلترة
            score = 40.0
            
            # 1. تقييم يعتمد على نوع وقوة الاستراتيجية (Max: +40)
            # الاستراتيجيات تمنح وزناً إضافياً بناءً على معطياتها الداخلية
            score += setup.get("confidence_boost", 0.0)
            
            # 2. تقييم التوافق مع الزخم اللحظي (Momentum Alignment) (Max: +10)
            rsi_5m = mtf_data['5m']['rsi']
            decision = setup.get("decision")
            
            if decision == "BUY":
                # زخم صاعد قوي ومستقر ولكن غير مفرط
                if 50.0 <= rsi_5m <= 65.0:
                    score += 10.0
                elif 65.0 < rsi_5m <= 75.0:
                    score += 5.0
            elif decision == "SELL":
                # زخم هابط قوي ومستقر ولكن غير مفرط
                if 35.0 <= rsi_5m <= 50.0:
                    score += 10.0
                elif 25.0 <= rsi_5m < 35.0:
                    score += 5.0
                    
            # 3. تقييم جودة بيئة السوق (Market Regime Quality) (Max: +10)
            # الاتجاهات الصريحة تمنح نقاطاً أعلى لاستراتيجيات الاتجاه، والنطاقات العرضية تدعم استراتيجية الارتداد
            regime = regime_data.get("regime")
            strategy_name = setup.get("name")
            
            if "TRENDING" in regime and strategy_name == "Trend_Continuation":
                score += 10.0
            elif regime == "RANGING" and strategy_name == "Range_Reversal":
                score += 10.0
            else:
                score += 2.0  # توافق مقبول ولكنه ليس مثالياً
                
            # ضمان بقاء النتيجة النهائية ضمن الحدود الرياضية المنطقية (0 - 100)
            final_score = max(0.0, min(score, 100.0))
            
            logger.info(f"📊 [محرك التقييم] تم حساب معامل الثقة للزوج {setup.get('symbol')}: {final_score:.1f}%")
            return float(final_score)
            
        except Exception as e:
            logger.error(f"خطأ غير متوقع أثناء حساب نقاط تقييم الصفقة: {str(e)}")
            return 0.0  # إرجاع صفر لإسقاط الصفقة فوراً كإجراء أمان
