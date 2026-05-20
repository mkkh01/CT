import asyncio
import json
import websockets
from config import BINANCE_WS_URL
from bot.trading import AIEngine  # تأكد من مطابقة مسار محرك الذكاء الاصطناعي لديك

class WhaleTracker:
    def __init__(self, bot=None, chat_id=None):
        self.bot = bot
        self.chat_id = chat_id
        self.tracking_symbols = set()  
        self.ai_engine = AIEngine(bot=bot, chat_id=chat_id)

    async def start_tracking(self, symbols: list):
        """بدء تتبع الحيتان الكبار لجميع عملات قاعدة البيانات الممررة"""
        self.tracking_symbols = {s.lower() for s in symbols}
        print(f"📡 [RADAR V3] انطلاق الرادار الديناميكي لمراقبة الحيتان لـ: {', '.join(self.tracking_symbols)}")
        await self._connect_websocket()

    async def _connect_websocket(self):
        """الاتصال بخدمة البث المباشر لـ Binance"""
        while True:
            try:
                streams = [f"{symbol}@trade" for symbol in self.tracking_symbols]
                if not streams:
                    print("⚠️ [RADAR V3] قاعدة البيانات فارغة من العملات، إعادة الفحص بعد 10 ثوانٍ...")
                    await asyncio.sleep(10)
                    continue

                uri = f"{BINANCE_WS_URL}/stream?streams={'/'.join(streams)}"
                print(f"🔌 [RADAR V3] جاري الاتصال بقنوات السيولة...")
                async with websockets.connect(uri) as ws:
                    print("✅ [RADAR V3] الرادار متصل ويراقب الحركات اللحظية الآن.")
                    while True:
                        message = await ws.recv()
                        await self._process_message(json.loads(message))
            except websockets.exceptions.ConnectionClosedOK:
                print("🔄 [RADAR V3] إعادة تدوير الاتصال الروتيني بالشبكة.")
            except Exception as e:
                print(f"❌ [RADAR V3] انقطاع في الشبكة الحية: {e}. إعادة المحاولة بعد 5 ثوانٍ...")
                await asyncio.sleep(5)

    async def _process_message(self, message):
        """تحليل الحركة وتصنيف الحيتان ديناميكياً حسب عمق السوق"""
        if 'stream' in message and 'data' in message:
            data = message['data']
            if data['e'] == 'trade':
                symbol = data['s'].upper()
                price = float(data['p'])
                quantity = float(data['q'])
                is_buyer_maker = data['m']

                # حساب الحجم الإجمالي للحركة بالدولار
                order_value_usd = price * quantity

                # 📊 تحديد الحد الأدنى ديناميكياً وحسب نوع وعمق سيولة العملة لمنع شلل البوت أو انهيار السيرفر
                if "BTC" in symbol or "ETH" in symbol:
                    min_threshold = 1000000.0  # مليون دولار للكبار (مثل البيتكوين والايثيريوم)
                elif any(m in symbol for m in ["XRP", "SOL", "BNB", "ADA", "DOGE"]):
                    min_threshold = 150000.0   # 150 ألف دولار للعملات المتوسطة القوية
                else:
                    min_threshold = 30000.0    # 30 ألف دولار فقط للعملات الصغيرة والصفرية (VTHO, SC, BB, POWR...)

                # إذا كانت حركة الحوت أقل من الحد المسموح به لهذه الفئة، يتم تخطيها فوراً
                if order_value_usd < min_threshold:
                    return

                # 🔍 كشف وتحليل طبيعة حركة الحوت (توزيع وتدوير أم بيع وشراء حقيقي بالماركت)
                if is_buyer_maker:
                    # طلبات صامتة (Limit Orders) أو توزيع كميات ونقلها بين محافظ
                    action_en = "DISTRIBUTION"
                    action_ar = "توزيع سيولة / نقل وتدوير بين المحافظ (صامت)"
                    is_market_trade = False
                else:
                    # طلبات ماركت فورية التهمت السيولة (Market Orders) وتؤثر على السعر حالاً
                    action_en = "BUY" if not is_buyer_maker else "SELL" # سيتم فلترتها لاحقاً للشراء أو البيع الفعلي
                    action_ar = "شراء حقيقي مباشر (تأثير فوري على السعر)" if not is_buyer_maker else "بيع حقيقي مباشر"
                    is_market_trade = True

                # صياغة رسالة الرادار المليوني للتليجرام
                whale_msg = (f"🐋 *تنبيه حركة حوت ذكية (V3)* 🐋\n\n"
                             f"🪙 العملة: {symbol}\n"
                             f"📊 طبيعة الحركة: {action_ar}\n"
                             f"💵 السعر اللحظي: ${price:,.8f}\n"
                             f"📦 الكمية المتداولة: {quantity:,.2f}\n"
                             f"💰 القيمة الإجمالية: ${order_value_usd:,.2f} USD\n"
                             f"⚡ التأثير المتوقع: {'قوي ومؤثر 🚀' if is_market_trade else 'تجميع وتدوير صامت 🔄'}")
                
                print(f"📥 [RADAR ALERT] {symbol} | القيمة: ${order_value_usd:,.2f} | النوع: {action_en}")

                if self.bot and self.chat_id:
                    try:
                        await self.bot.send_message(chat_id=self.chat_id, text=whale_msg, parse_mode='Markdown')
                    except Exception as e:
                        print(f"❌ [RADAR V3] فشل إرسال التنبيه للتليجرام: {e}")

                # 🚀 تمرير البيانات لمحرك الذكاء الاصطناعي للتحليل والتدريب الذاتي
                try:
                    # نمرر الحركة الفعلية للمحرك، وإذا كانت مجرد نقل وتوزيع يستفيد منها كبيانات للتعلم والتدريب الصامت
                    asyncio.create_task(
                        self.ai_engine.analyze_and_trade(
                            symbol=symbol, 
                            current_price=price, 
                            atr=0.0, 
                            whale_action="BUY" if (is_market_trade and not is_buyer_maker) else ("SELL" if is_market_trade else "HOLD")
                        )
                    )
                except Exception as ai_err:
                    print(f"🚨 [RADAR V3] فشل تمرير البيانات لمحرك التدريب والتحليل: {ai_err}")

    def add_symbol(self, symbol: str):
        self.tracking_symbols.add(symbol.lower())
        print(f"➕ [RADAR V3] إضافة {symbol} للمراقبة.")

    def remove_symbol(self, symbol: str):
        self.tracking_symbols.discard(symbol.lower())
        print(f"🗑️ [RADAR V3] حذف {symbol} من الرادار.")

    async def update_tracking_symbols(self, new_symbols: list):
        self.tracking_symbols = {s.lower() for s in new_symbols}
        print(f"🔄 [RADAR V3] تحديث كامل للرادار لجميع عملات قاعدة البيانات المتاحة.")
