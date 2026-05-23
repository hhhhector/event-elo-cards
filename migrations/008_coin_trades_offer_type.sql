ALTER TABLE discord_tcg.coin_trades
    ADD COLUMN offer_type VARCHAR(4) NOT NULL DEFAULT 'sell';
