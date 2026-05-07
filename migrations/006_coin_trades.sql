CREATE TABLE IF NOT EXISTS discord_tcg.coin_trades (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    seller_id   TEXT NOT NULL,
    buyer_id    TEXT NOT NULL,
    card_id     UUID NOT NULL,
    coin_amount INTEGER NOT NULL CHECK (coin_amount > 0),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '5 minutes',
    resolved    BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_coin_trades_lookup
    ON discord_tcg.coin_trades (seller_id, buyer_id, card_id, coin_amount)
    WHERE resolved = FALSE;

ALTER TABLE discord_tcg.coin_trades ENABLE ROW LEVEL SECURITY;
CREATE POLICY bot_all ON discord_tcg.coin_trades FOR ALL USING (true) WITH CHECK (true);
