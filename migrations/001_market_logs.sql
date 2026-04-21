-- Market logging tables for discord_tcg schema.
-- Run this once in the Supabase SQL editor.

-- Registered_at on users (backfill from last_active where possible)
ALTER TABLE discord_tcg.users
    ADD COLUMN IF NOT EXISTS registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

UPDATE discord_tcg.users
SET registered_at = last_active
WHERE last_active IS NOT NULL AND registered_at > last_active;

-- Auctions: one row per drop
CREATE TABLE IF NOT EXISTS discord_tcg.auctions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    duration_seconds INT NOT NULL
);

-- One row per card in a drop
CREATE TABLE IF NOT EXISTS discord_tcg.auction_cards (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auction_id UUID NOT NULL REFERENCES discord_tcg.auctions(id) ON DELETE CASCADE,
    player_uuid UUID NOT NULL,
    rating NUMERIC NOT NULL,
    rank INT,
    bank_value INT NOT NULL,
    min_bid INT NOT NULL,
    min_increment INT NOT NULL,
    winner_id TEXT,
    winning_bid INT,
    bid_count INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_auction_cards_auction_id ON discord_tcg.auction_cards(auction_id);
CREATE INDEX IF NOT EXISTS idx_auction_cards_player_uuid ON discord_tcg.auction_cards(player_uuid);
CREATE INDEX IF NOT EXISTS idx_auction_cards_winner_id ON discord_tcg.auction_cards(winner_id);

-- One row per bid
CREATE TABLE IF NOT EXISTS discord_tcg.bids (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auction_card_id UUID NOT NULL REFERENCES discord_tcg.auction_cards(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    amount INT NOT NULL,
    placed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    was_winner BOOLEAN NOT NULL DEFAULT FALSE,
    was_refunded BOOLEAN NOT NULL DEFAULT FALSE,
    refunded_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_bids_auction_card_id ON discord_tcg.bids(auction_card_id);
CREATE INDEX IF NOT EXISTS idx_bids_user_id ON discord_tcg.bids(user_id);
CREATE INDEX IF NOT EXISTS idx_bids_placed_at ON discord_tcg.bids(placed_at);

-- One row per bank sale
CREATE TABLE IF NOT EXISTS discord_tcg.sales (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    player_uuid UUID NOT NULL,
    rating NUMERIC NOT NULL,
    rank INT,
    sale_price INT NOT NULL,
    held_seconds INT NOT NULL,
    sold_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sales_user_id ON discord_tcg.sales(user_id);
CREATE INDEX IF NOT EXISTS idx_sales_player_uuid ON discord_tcg.sales(player_uuid);
CREATE INDEX IF NOT EXISTS idx_sales_sold_at ON discord_tcg.sales(sold_at);

-- One row per dividend payout per user
CREATE TABLE IF NOT EXISTS discord_tcg.dividend_payouts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    amount INT NOT NULL,
    paid_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_dividend_payouts_user_id ON discord_tcg.dividend_payouts(user_id);
CREATE INDEX IF NOT EXISTS idx_dividend_payouts_paid_at ON discord_tcg.dividend_payouts(paid_at);

-- RLS enable + permissive policy (bot is the only writer/reader)
ALTER TABLE discord_tcg.auctions ENABLE ROW LEVEL SECURITY;
ALTER TABLE discord_tcg.auction_cards ENABLE ROW LEVEL SECURITY;
ALTER TABLE discord_tcg.bids ENABLE ROW LEVEL SECURITY;
ALTER TABLE discord_tcg.sales ENABLE ROW LEVEL SECURITY;
ALTER TABLE discord_tcg.dividend_payouts ENABLE ROW LEVEL SECURITY;

CREATE POLICY bot_all ON discord_tcg.auctions FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY bot_all ON discord_tcg.auction_cards FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY bot_all ON discord_tcg.bids FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY bot_all ON discord_tcg.sales FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY bot_all ON discord_tcg.dividend_payouts FOR ALL USING (true) WITH CHECK (true);
