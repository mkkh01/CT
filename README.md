# CT Trading System v1.3
Spot trading engine — Balanced mode — 1D → 4H → 1H — Target 1% / SL 0.4% — ≥82% winrate design.

**Render commands (already set):**
- Build: `pip install -r requirements.txt`
- Start: `python main.py`

**Required env vars (your existing names):**
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `REDIS_URL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID` (also aliased to TELEGRAM_ADMIN_ID)
- Optional: `SYMBOL_LIST=BTC/USDT,ETH/USDT,SOL/USDT`

**Features:**
- Public Binance WebSocket only — no exchange API keys
- EMA / RSI(7) / ATR / Swing H:L / Order Block / FVG detection
- Time filter (07:30–19:30 UTC), ATR% filter, cooldown rules
- Telegram signals + `/status` `/symbols` commands
- Supabase logging + Redis risk state
