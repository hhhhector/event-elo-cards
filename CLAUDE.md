# event-elo-cards

Discord TCG bot ("Telo"). Reads `event_elo`, owns the `discord_tcg` schema.

## Structure
- `main.py` — entry point, loads cogs.
- `src/database.py` — all Supabase access (asyncpg via pgbouncer transaction pooler).
- `src/cogs/auction.py` — drop cadence, auction view, bidding.
- `src/cogs/economy.py` — `/bank` (sell), balance, faucet dividends.
- `src/cogs/inventory.py` — `/inv`, `/view`.
- `src/cogs/stats.py` — player/card lookups.
- `src/utils/economy_utils.py` — bank value, yield, min bid, rarity formulas.

## Schema ownership
- Owns: `discord_tcg.users`, `discord_tcg.cards`, `discord_tcg.system_state`.
- Reads only: `event_elo.players` (for drops, card metadata, ratings).

## Deployment
Railway, from the `event-elo-cards` subdir. Procfile defines the process.

## Known gotchas
- **pgbouncer transaction pooler** requires `statement_cache_size=0` in asyncpg.
- **`discord.ui.View` timeout resets on every interaction** — never rely on `timeout=` alone to close an auction. Schedule an explicit `asyncio.create_task` force-close and guard with a `_closed` flag to prevent double-execution.
- **Concurrent bids** on the same card can double-deduct without a lock. Use `asyncio.Lock` per player UUID on the auction view.
- **New tables need RLS policies** or the bot can't read/write them.
- **`.in()` with many UUIDs** can silently truncate — see `feedback_supabase_gotchas.md`.
- **`system_state.is_active` stuck True** blocks all drops. If the bot crashes mid-auction, reset manually.

## Game design
Economy parameters, drop cadence, auction rules live in `Esports Trading Card Economy Design.md` and the root `docs/` folder. Read those before touching balance.
