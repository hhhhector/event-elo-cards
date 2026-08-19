# event-elo-cards

Discord TCG bot ("Telo"). Reads `event_elo`, owns the `discord_tcg` schema.

## Structure
- `main.py` — thin shim, calls `src.main.main()`.
- `src/main.py` — real entry point. Defines `TCG_Bot`, connects the DB, loads cogs, syncs the command tree.
- `src/config.py` — env vars. `DEV_GUILD_ID` set → commands sync to that guild instantly; unset → global sync.
- `src/database.py` — all Supabase access (asyncpg via pgbouncer transaction pooler). Single class, ~950 lines, every query lives here.
- `src/cogs/auction.py` — drop loop, auction view, bid modal, `/pingme`.
- `src/cogs/economy.py` — `/register`, `/bank` (sell), `/bal`, `/upgradeinventory`, daily dividend faucet.
- `src/cogs/inventory.py` — `/inv`, `/view`, `/archive`, `/burn`.
- `src/cogs/stats.py` — `/rank`, `/whohas`, `/updaterole`, plus the auto-updating stats message and wealth-role loop.
- `src/cogs/market.py` — `/sell` and `/buy` (card for coins, peer to peer).
- `src/cogs/trade.py` — `/trade` (card for card).
- `src/cogs/wishlist.py` — `/wishlist` add/remove/view; wishlisted players ping their watchers on drop.
- `src/utils/economy_utils.py` — bank value, yield, min bid, rarity, roster caps, sell-hold window.
- `src/utils/card_generator.py` — calls the satori API for card PNGs, stitches multi-card grids with Pillow.
- `src/utils/autocomplete.py` — slash-command autocomplete for card IDs and player names.
- `ban_player.py` — standalone admin script. Bans a player and refunds every holder, walking a five-step refund-price ladder. Writes an audit file to `ban_logs/`.
- `migrations/` — numbered `.sql`, applied by hand in the Supabase SQL editor.

## Schema ownership
- Owns everything in `discord_tcg`: `users`, `cards`, `system_state`, `auctions`, `auction_cards`, `bids`, `sales`, `dividend_payouts`, `market_kpi_snapshots`, `trades`, `coin_trades`, `archived_cards`, `wishlists`.
- Reads only: `event_elo.players` (for drops, card metadata, ratings).

## External dependency
Card images come from `event-elo-satori` over HTTP (`API_BASE_URL` in `card_generator.py`). It's stateless and takes stats as query params. If it's down, `_send_drop` raises and the drop is skipped.

## Deployment
Railway, from the `event-elo-cards` subdir. `Procfile` runs it as a worker process.

## Known gotchas
- **pgbouncer transaction pooler** requires `statement_cache_size=0` in asyncpg.
- **`discord.ui.View` timeout resets on every interaction** — never rely on `timeout=` alone to close an auction. `_send_drop` schedules an explicit `asyncio.create_task(self._force_close_auction(...))` and `AuctionView` guards with a `_closed` flag to prevent double-execution.
- **Concurrent bids** on the same card can double-deduct without a lock. `AuctionView` holds an `asyncio.Lock` per player UUID (`bid_locks`).
- **Defer before taking the lock.** `BidModal.on_submit` calls `interaction.response.defer()` first so the 3-second ACK deadline is met regardless of lock contention or DB latency.
- **New tables need RLS policies** or the bot can't read/write them. Every migration ends with `ENABLE ROW LEVEL SECURITY` + a permissive `bot_all` policy.
- **`system_state.is_active` stuck True** blocks all drops. `before_drop_loop` resets it on boot, and `on_drop_loop_error` resets it on crash, but a hard kill outside those paths needs a manual reset.
- **`.in()` with many UUIDs** can silently truncate — see `feedback_supabase_gotchas.md`.
- **Bank value is duplicated in three places**: `economy_utils.calculate_bank_value`, the `POWER(...)` expression in `database.process_faucet_dividends`, and `ban_player.calculate_bank_value`. Yield rates are duplicated between `economy_utils.YIELD_RATES` and the `CASE` in `process_faucet_dividends`. Change one, change all.

## Stale auctions (fixed 2026-08-19)
`closed_at` is only ever set by `finalize_auction`, which only runs from `AuctionView.on_timeout`. A hard kill mid-auction (Railway redeploy, crash, OOM) skips it, leaving `closed_at IS NULL` forever. Because `user_has_active_bid()` filters on `closed_at IS NULL AND was_refunded = FALSE`, the affected bidders are permanently blocked from `/buy` and `/sell`.

`migrations/009` was supposed to repair this but referenced `auctions.created_at` when the column is `fired_at`, so it errored on every attempt and never ran. Now fixed, and `Database.close_stale_auctions()` runs on every boot from `before_drop_loop` alongside the `is_active` reset, so it self-heals.

**Still outstanding:** closing the row unblocks the user but doesn't return their money. Coins are deducted at bid time and only returned on outbid or awarded at close, so a crashed auction leaves the highest bidder charged with no card and no refund. See the diagnostic query in the project notes before deciding whether to backfill refunds.

## Game design
Economy parameters, drop cadence, and auction rules live in `Esports Trading Card Economy Design.md` in this directory. Read it before touching balance, and update it in the same commit when you change a number.
