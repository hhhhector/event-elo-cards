-- Close auctions whose natural end time has passed but closed_at was never set
-- (bot crashed mid-auction before on_timeout could call finalize_auction).
-- Without this, user_has_active_bid() treats bids on these auctions as live.

UPDATE discord_tcg.auctions
SET closed_at = created_at + (duration_seconds || ' seconds')::interval
WHERE closed_at IS NULL
  AND created_at + (duration_seconds || ' seconds')::interval < NOW();
