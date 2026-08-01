-- Migration: 007_spot_only_constraint
-- Description: Update simulated_trades direction check to only allow 'long' (Spot-only).

-- 1. Remove the old constraint if it exists.
-- Note: In PostgreSQL/Supabase, we need the constraint name. 
-- Based on 001_init_core_tables.sql, it was likely an inline check.
-- We will try to drop it by name if we can find it, or just add a new one.

DO $$
BEGIN
    -- Try to drop the existing constraint if we can identify it.
    -- Inline constraints are often named like 'simulated_trades_direction_check'.
    ALTER TABLE simulated_trades DROP CONSTRAINT IF EXISTS simulated_trades_direction_check;
EXCEPTION
    WHEN undefined_object THEN
        NULL;
END $$;

-- 2. Add the new Spot-only constraint.
ALTER TABLE simulated_trades 
ADD CONSTRAINT simulated_trades_direction_check 
CHECK (direction = 'long');

-- 3. Update any existing 'short' trades to 'long' or just leave them (they will fail future updates if not handled).
-- For safety in this simulation, we leave existing data but enforce new data.
