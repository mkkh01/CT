import asyncio
from sqlalchemy import text
from database import engine

async def migrate():
    async with engine.begin() as conn:
        print("🔍 Checking and updating shadow_trades_v4 table...")
        
        # قائمة بالأعمدة الجديدة التي نحتاج لإضافتها
        columns_to_add = [
            ("entry_price", "DOUBLE PRECISION DEFAULT 0.0"),
            ("stop_loss", "DOUBLE PRECISION"),
            ("take_profit", "DOUBLE PRECISION"),
            ("status", "VARCHAR DEFAULT 'OPEN'"),
            ("closed_at", "TIMESTAMP")
        ]
        
        for col_name, col_type in columns_to_add:
            try:
                await conn.execute(text(f"ALTER TABLE shadow_trades_v4 ADD COLUMN {col_name} {col_type};"))
                print(f"✅ Added column: {col_name}")
            except Exception as e:
                if "already exists" in str(e):
                    print(f"ℹ️ Column {col_name} already exists, skipping.")
                else:
                    print(f"⚠️ Error adding {col_name}: {e}")
        
        print("🚀 Migration completed!")

if __name__ == "__main__":
    asyncio.run(migrate())
