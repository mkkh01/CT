-- Run this in Supabase SQL Editor
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE TABLE IF NOT EXISTS public.users (
    id UUID REFERENCES auth.users(id) PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    full_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS public.system_config (
    id BIGSERIAL PRIMARY KEY,
    system_enabled BOOLEAN NOT NULL DEFAULT true,
    tp_pct NUMERIC(10,4) NOT NULL DEFAULT 1.00,
    sl_pct NUMERIC(10,4) NOT NULL DEFAULT 0.40,
    timeout_hours INT NOT NULL DEFAULT 12,
    trading_start_utc TIME NOT NULL DEFAULT '07:30:00',
    trading_end_utc TIME NOT NULL DEFAULT '19:30:00',
    min_atr_pct NUMERIC(10,4) NOT NULL DEFAULT 0.15,
    max_atr_pct NUMERIC(10,4) NOT NULL DEFAULT 0.70,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
INSERT INTO public.system_config DEFAULT VALUES ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS public.user_assets (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    allocated_usdt NUMERIC(18,2) NOT NULL DEFAULT 0.00,
    is_enabled BOOLEAN NOT NULL DEFAULT true,
    sharia_compliant BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, symbol)
);
CREATE TABLE IF NOT EXISTS public.trading_signals (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'system',
    symbol TEXT NOT NULL,
    trigger_price NUMERIC(18,8) NOT NULL,
    tp_price NUMERIC(18,8) NOT NULL,
    sl_price NUMERIC(18,8) NOT NULL,
    tf_1d_pass BOOLEAN NOT NULL, tf_4h_pass BOOLEAN NOT NULL, tf_1h_pass BOOLEAN NOT NULL,
    ob_zone NUMERIC[], fvg_zone NUMERIC[],
    rsi_4h NUMERIC(10,4), rsi_1h NUMERIC(10,4), atr_pct NUMERIC(10,4),
    in_trading_hours BOOLEAN NOT NULL,
    signal_hash TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'NEW',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS public.orders (
    id BIGSERIAL PRIMARY KEY,
    signal_id BIGINT REFERENCES public.trading_signals(id),
    symbol TEXT NOT NULL,
    entry_price NUMERIC(18,8) NOT NULL,
    tp_price NUMERIC(18,8) NOT NULL,
    sl_price NUMERIC(18,8) NOT NULL,
    quantity NUMERIC(18,8) NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'OPEN',
    close_price NUMERIC(18,8), profit_pct NUMERIC(10,4),
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_signals_hash ON public.trading_signals(signal_hash);
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON public.orders(symbol);
