import asyncpg
from typing import Optional, List

class Database:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @classmethod
    async def create(cls, dsn: str):
        # Disable statement cache because Supabase transaction pooler (pgbouncer) doesn't support prepared statements
        pool = await asyncpg.create_pool(dsn, statement_cache_size=0)
        return cls(pool)

    async def close(self):
        await self.pool.close()

    # --- event_elo (Read-Only) ---

    async def get_random_unbanned_players(self, limit: int = 4) -> List[asyncpg.Record]:
        query = """
        SELECT 
            uuid, 
            current_name, 
            current_drating, 
            current_rank, 
            peak_drating AS peak_rating, 
            peak_rank,
            is_banned
        FROM event_elo.players
        WHERE is_banned = FALSE
        ORDER BY random()
        LIMIT $1
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, limit)

    # --- discord_tcg (Read/Write) ---

    async def register_user(self, discord_id: int, starting_balance: int) -> bool:
        query = """
        INSERT INTO discord_tcg.users (discord_id, coins, last_active)
        VALUES ($1, $2, CURRENT_TIMESTAMP)
        ON CONFLICT (discord_id) DO NOTHING
        """
        async with self.pool.acquire() as conn:
            status = await conn.execute(query, str(discord_id), starting_balance)
            return status == "INSERT 0 1"  # asyncpg returns "INSERT 0 1" on success, "INSERT 0 0" on conflict

    async def get_user_coins(self, discord_id: int) -> Optional[int]:
        query = "SELECT coins FROM discord_tcg.users WHERE discord_id = $1"
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, str(discord_id))

    async def get_user_roster_info(self, discord_id: int) -> Optional[asyncpg.Record]:
        query = "SELECT coins, roster_cap FROM discord_tcg.users WHERE discord_id = $1"
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, str(discord_id))

    async def get_card_count(self, discord_id: int) -> int:
        query = "SELECT COUNT(*) FROM discord_tcg.cards WHERE owner_id = $1"
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, str(discord_id))

    async def update_user_coins(self, discord_id: int, delta: int) -> Optional[int]:
        query = """
        UPDATE discord_tcg.users
        SET coins = coins + $2, last_active = CURRENT_TIMESTAMP
        WHERE discord_id = $1
        RETURNING coins
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, str(discord_id), delta)

    async def get_user_cards(self, discord_id: int) -> List[asyncpg.Record]:
        # Join cards with players to get the drating & name
        query = """
        SELECT c.id as card_id, c.player_uuid, c.acquired_at, p.current_name, p.current_drating, p.current_rank
        FROM discord_tcg.cards c
        JOIN event_elo.players p ON c.player_uuid = p.uuid
        WHERE c.owner_id = $1
        ORDER BY p.current_drating DESC
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, str(discord_id))

    async def add_card_to_user(self, owner_id: int, player_uuid: str) -> int:
        query = """
        INSERT INTO discord_tcg.cards (owner_id, player_uuid, acquired_at)
        VALUES ($1, $2, CURRENT_TIMESTAMP)
        RETURNING id
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, str(owner_id), player_uuid)

    async def get_random_player_in_rank_range(self, min_rank: int, max_rank: Optional[int] = None) -> Optional[asyncpg.Record]:
        query = f"""
        SELECT 
            uuid, 
            current_name, 
            current_drating, 
            current_rank, 
            peak_drating AS peak_rating, 
            peak_rank
        FROM event_elo.players
        WHERE is_banned = FALSE
        AND current_rank >= $1
        {"AND current_rank <= $2" if max_rank else ""}
        ORDER BY random()
        LIMIT 1
        """
        async with self.pool.acquire() as conn:
            if max_rank:
                return await conn.fetchrow(query, min_rank, max_rank)
            return await conn.fetchrow(query, min_rank)

    async def get_player_extended_stats(self, player_uuid: str) -> Optional[asyncpg.Record]:
        query = """
        SELECT 
            uuid,
            current_name,
            current_drating,
            current_rank,
            peak_drating AS peak_rating,
            peak_rank
        FROM event_elo.players
        WHERE uuid = $1
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, player_uuid)

    async def get_card_by_id(self, card_id: str, owner_id: int) -> Optional[asyncpg.Record]:
        query = """
        SELECT c.id as card_id, c.player_uuid, c.acquired_at, p.current_name, p.current_drating
        FROM discord_tcg.cards c
        JOIN event_elo.players p ON c.player_uuid = p.uuid
        WHERE c.id = $1 AND c.owner_id = $2
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, card_id, str(owner_id))

    async def sell_card_to_bank(self, card_id: str, owner_id: int, sale_price: int) -> Optional[int]:
        """Atomically remove card and credit coins. Returns new balance or None if card not found."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                deleted = await conn.execute(
                    "DELETE FROM discord_tcg.cards WHERE id = $1 AND owner_id = $2",
                    card_id, str(owner_id)
                )
                if deleted != "DELETE 1":
                    return None
                return await conn.fetchval(
                    "UPDATE discord_tcg.users SET coins = coins + $1, last_active = CURRENT_TIMESTAMP WHERE discord_id = $2 RETURNING coins",
                    sale_price, str(owner_id)
                )

    async def remove_card(self, card_id: str, owner_id: int) -> bool:
        query = """
        DELETE FROM discord_tcg.cards
        WHERE id = $1 AND owner_id = $2
        """
        async with self.pool.acquire() as conn:
            status = await conn.execute(query, card_id, str(owner_id))
            return status == "DELETE 1"

    async def get_system_state(self) -> Optional[asyncpg.Record]:
        query = "SELECT next_drop_timestamp, next_dividend_timestamp, is_active FROM discord_tcg.system_state WHERE id = 1"
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query)

    async def set_next_dividend_timestamp(self, ts) -> None:
        query = "UPDATE discord_tcg.system_state SET next_dividend_timestamp = $1 WHERE id = 1"
        async with self.pool.acquire() as conn:
            await conn.execute(query, ts)

    async def set_next_drop_timestamp(self, ts) -> None:
        query = """
        UPDATE discord_tcg.system_state
        SET next_drop_timestamp = $1
        WHERE id = 1
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, ts)

    async def set_auction_active(self, active: bool) -> None:
        query = "UPDATE discord_tcg.system_state SET is_active = $1 WHERE id = 1"
        async with self.pool.acquire() as conn:
            await conn.execute(query, active)

    async def process_faucet_dividends(self):
        # Calculate dividend: SUM(10000 * (rating / 2200)^3) / 10
        query = """
        WITH UserDividends AS (
            SELECT
                c.owner_id,
                SUM(10000.0 * POWER(p.current_drating / 2200.0, 3)) / 10.0 AS dividend
            FROM discord_tcg.cards c
            JOIN event_elo.players p ON c.player_uuid = p.uuid
            WHERE p.is_banned = FALSE
            GROUP BY c.owner_id
        )
        UPDATE discord_tcg.users u
        SET coins = u.coins + ud.dividend
        FROM UserDividends ud
        WHERE u.discord_id = ud.owner_id;
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query)
