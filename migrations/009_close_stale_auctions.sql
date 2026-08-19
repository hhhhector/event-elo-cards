-- Close auctions whose natural end time has passed but closed_at was never set
-- (bot crashed mid-auction before on_timeout could call finalize_auction).
-- Without this, user_has_active_bid() treats bids on these auctions as live,
-- which permanently blocks the affected bidders from /buy and /sell.
--
-- NOTE: the first version of this migration referenced auctions.created_at,
-- which does not exist — the column is fired_at (see 001_market_logs.sql).
-- It errored on every attempt and never ran. Fixed 2026-08-19.
--
-- Safe to re-run. The bot also does this automatically on boot now
-- (Database.close_stale_auctions, called from Auction.before_drop_loop),
-- so this file is only needed for the one-time backfill.

UPDATE discord_tcg.auctions
SET closed_at = fired_at + make_interval(secs => duration_seconds)
WHERE closed_at IS NULL
  AND fired_at + make_interval(secs => duration_seconds) < NOW();
