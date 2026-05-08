ALTER TABLE discord_tcg.cards
    ADD COLUMN facing_misprint BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE discord_tcg.archived_cards
    ADD COLUMN facing_misprint BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE discord_tcg.auction_cards
    ADD COLUMN facing_misprint BOOLEAN NOT NULL DEFAULT FALSE;
