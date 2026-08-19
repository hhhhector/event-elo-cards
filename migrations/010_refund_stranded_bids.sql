-- Refund bids stranded by auctions that crashed before closing.
--
-- Coins are deducted the moment a bid is placed. They return either when the
-- bidder is outbid (Database.refund_bid) or become a card when the auction
-- closes (AuctionView.on_timeout). If the bot is killed mid-auction neither
-- happens, so the top bidder on each card is left charged with nothing.
--
-- Never-finalized cards are identified by bid_count = 0, because
-- finalize_auction_card is what populates that column. The fired_at condition
-- excludes auctions that are still legitimately running.
--
-- Naturally idempotent: once refunded, was_refunded = TRUE excludes the rows,
-- so a second run credits nobody and returns zero rows.
--
-- One statement on purpose. An earlier version used a TEMP TABLE, which the
-- Supabase SQL editor drops between statements ("relation does not exist").
-- Data-modifying CTEs are executed exactly once and always to completion, and
-- every branch reads the same snapshot, so this is atomic without an explicit
-- transaction block.
--
-- Run 009 first (it clears the /buy and /sell lockout).
-- Measured 2026-08-19 before running: 3 users, 5,104 coins.

WITH stranded AS (
    SELECT b.id, b.user_id, b.amount
    FROM discord_tcg.bids b
    JOIN discord_tcg.auction_cards ac ON b.auction_card_id = ac.id
    JOIN discord_tcg.auctions a       ON ac.auction_id = a.id
    WHERE b.was_refunded = FALSE
      AND ac.winner_id IS NULL
      AND ac.bid_count = 0
      AND a.fired_at + make_interval(secs => a.duration_seconds) < NOW()
),
owed AS (
    SELECT user_id, SUM(amount) AS amount, COUNT(*) AS bids
    FROM stranded
    GROUP BY user_id
),
credited AS (
    UPDATE discord_tcg.users u
    SET coins = u.coins + o.amount
    FROM owed o
    WHERE u.discord_id = o.user_id
    RETURNING u.discord_id, o.amount, o.bids
),
marked AS (
    UPDATE discord_tcg.bids b
    SET was_refunded = TRUE,
        refunded_at  = NOW()
    FROM stranded s
    WHERE b.id = s.id
    RETURNING b.id
)
SELECT c.discord_id                     AS user_id,
       c.bids                           AS bids_refunded,
       c.amount                         AS coins_returned,
       (SELECT COUNT(*) FROM marked)    AS total_bids_marked
FROM credited c
ORDER BY c.amount DESC;
