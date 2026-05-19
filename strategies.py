# core/strategies.py

class SpotStrategies:
    @staticmethod
    def dynamic_dca(entry_price: float, current_price: float, drop_percentage: float = 0.05) -> bool:
        """
        متوسط التكلفة الديناميكي: لا يشتري إلا إذا هبط السعر بنسبة معينة (مثلاً 5%)
        """
        price_drop = (entry_price - current_price) / entry_price
        if price_drop >= drop_percentage:
            return True
        return False

    @staticmethod
    def smart_grid_levels(current_price: float, atr: float, grid_count: int = 5) -> list:
        """
        حساب مستويات الشراء والبيع لشبكة التداول بناءً على التذبذب (ATR)
        """
        step = atr / 2
        buy_levels = [current_price - (step * i) for i in range(1, grid_count + 1)]
        sell_levels = [current_price + (step * i) for i in range(1, grid_count + 1)]
        
        return {"buy_levels": buy_levels, "sell_levels": sell_levels}
