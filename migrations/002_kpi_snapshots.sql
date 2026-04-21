-- Market KPI snapshots for the rolling chart on the stats message.
-- Run in the Supabase SQL editor after 001_market_logs.sql.

CREATE TABLE IF NOT EXISTS discord_tcg.market_kpi_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    taken_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    rarity TEXT NOT NULL,
    median_wb_over_bv NUMERIC,
    sample_size INT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kpi_snapshots_taken_at ON discord_tcg.market_kpi_snapshots(taken_at);

ALTER TABLE discord_tcg.market_kpi_snapshots ENABLE ROW LEVEL SECURITY;
CREATE POLICY bot_all ON discord_tcg.market_kpi_snapshots FOR ALL USING (true) WITH CHECK (true);
