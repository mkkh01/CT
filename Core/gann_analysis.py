import math
import pandas as pd

class GannAnalyzer:
    def __init__(self):
        pass

    def calculate_gann_square_of_9(self, price):
        """حساب مستويات مربع التسعة (Gann Square of 9) للسعر الحالي"""
        root = math.sqrt(price)
        # الزوايا الرئيسية بالدرجات (45, 90, 180, 270, 360)
        angles = [45, 90, 135, 180, 225, 270, 315, 360]
        levels = {}
        for angle in angles:
            # المعادلة: (جذر السعر + (الزاوية / 180))^2
            level = math.pow(root + (angle / 180), 2)
            levels[angle] = level
        return levels

    def get_gann_bias(self, df: pd.DataFrame):
        """تحديد الانحياز الزمني والسعري بناءً على زوايا جان"""
        current_price = df['close'].iloc[-1]
        levels = self.calculate_gann_square_of_9(current_price)
        
        # البحث عن أقرب مستوى دعم ومقاومة من مربع التسعة
        resistance = min([v for v in levels.values() if v > current_price])
        support = max([v for v in levels.values() if v < current_price])
        
        # إذا كان السعر قريباً جداً من زاوية 360 أو 180، فهناك احتمال انعكاس كبير
        dist_to_res = (resistance - current_price) / current_price
        if dist_to_res < 0.005: # أقل من 0.5% من المقاومة
            return "BEARISH_REVERSAL_ZONE"
            
        return "BULLISH_CONTINUATION" if current_price > support else "NEUTRAL"
