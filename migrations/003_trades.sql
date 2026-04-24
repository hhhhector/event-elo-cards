-- Trade history table.
-- No FK on card IDs — cards get deleted on bank sale, but resolved trades are historical.
-- player_uuid columns are the durable snapshot for history.
-- Run once in the Supabase SQL editor.

CREATE TABLE IF NOT EXISTS discord_tcg.trades (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    proposer_id      TEXT        NOT NULL,
    receiver_id      TEXT        NOT NULL,
    proposer_card_id UUID        NOT NULL,
    proposer_player_uuid UUID    NOT NULL,
    receiver_card_id UUID        NOT NULL,
    receiver_player_uuid UUID    NOT NULL,
    resolved         BOOLEAN     NOT NULL DEFAULT FALSE,
    proposed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_trades_proposer_id   ON discord_tcg.trades(proposer_id);
CREATE INDEX IF NOT EXISTS idx_trades_receiver_id   ON discord_tcg.trades(receiver_id);
CREATE INDEX IF NOT EXISTS idx_trades_proposed_at   ON discord_tcg.trades(proposed_at);

ALTER TABLE discord_tcg.trades ENABLE ROW LEVEL SECURITY;
CREATE POLICY bot_all ON discord_tcg.trades FOR ALL USING (true) WITH CHECK (true);
