-- Archived cards: permanently removed from active roster.
-- 0 yield, can't be sold or traded, don't count toward roster cap.
-- Card UUID is preserved from discord_tcg.cards.
-- Run once in the Supabase SQL editor.

CREATE TABLE IF NOT EXISTS discord_tcg.archived_cards (
    id          UUID        PRIMARY KEY,
    owner_id    TEXT        NOT NULL,
    player_uuid UUID        NOT NULL,
    acquired_at TIMESTAMPTZ NOT NULL,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_archived_cards_owner_id   ON discord_tcg.archived_cards(owner_id);
CREATE INDEX IF NOT EXISTS idx_archived_cards_player_uuid ON discord_tcg.archived_cards(player_uuid);

ALTER TABLE discord_tcg.archived_cards ENABLE ROW LEVEL SECURITY;
CREATE POLICY bot_all ON discord_tcg.archived_cards FOR ALL USING (true) WITH CHECK (true);
