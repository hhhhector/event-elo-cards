-- Wishlist: users opt-in to ping notifications for specific players.
-- Run once in the Supabase SQL editor.

CREATE TABLE IF NOT EXISTS discord_tcg.wishlists (
    discord_id  TEXT NOT NULL,
    player_uuid UUID NOT NULL,
    PRIMARY KEY (discord_id, player_uuid)
);

CREATE INDEX IF NOT EXISTS idx_wishlists_player_uuid ON discord_tcg.wishlists(player_uuid);

ALTER TABLE discord_tcg.wishlists ENABLE ROW LEVEL SECURITY;
CREATE POLICY bot_all ON discord_tcg.wishlists FOR ALL USING (true) WITH CHECK (true);
