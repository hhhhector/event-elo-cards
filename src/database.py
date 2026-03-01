import asyncpg
from typing import Optional, List

class Database:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @classmethod
    async def create(cls, dsn: str):
        pool = await asyncpg.create_pool(dsn)
        return cls(pool)

    async def close(self):
        await self.pool.close()

    # --- event_elo (Read-Only) ---

    async def get_player_by_uuid(self, player_uuid: str) -> Optional[asyncpg.Record]:
        query = """
        SELECT uuid, current_name, current_rating, current_rd, current_drating, is_banned
        FROM event_elo.players
        WHERE uuid = $1
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query, player_uuid)

    async def get_random_unbanned_players(self, limit: int = 4) -> List[asyncpg.Record]:
        query = """
        SELECT uuid, current_name, current_rating, current_rd, current_drating, is_banned
        FROM event_elo.players
        WHERE is_banned = FALSE
        ORDER BY random()
        LIMIT $1
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, limit)

    # --- discord_tcg (Read/Write) ---

    async def ensure_user(self, discord_id: int):
        query = """
        INSERT INTO discord_tcg.users (discord_id, coins, last_active)
        VALUES ($1, 0, CURRENT_TIMESTAMP)
        ON CONFLICT (discord_id) DO UPDATE SET last_active = CURRENT_TIMESTAMP
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, str(discord_id))

    async def get_user_coins(self, discord_id: int) -> int:
        await self.ensure_user(discord_id)
        query = "SELECT coins FROM discord_tcg.users WHERE discord_id = $1"
        async with self.pool.acquire() as conn:
            val = await conn.fetchval(query, str(discord_id))
            return val if val is not None else 0

    async def update_user_coins(self, discord_id: int, delta: int) -> int:
        await self.ensure_user(discord_id)
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
        SELECT c.id as card_id, c.player_uuid, c.acquired_at, p.current_name, p.current_drating
        FROM discord_tcg.cards c
        JOIN event_elo.players p ON c.player_uuid = p.uuid
        WHERE c.owner_id = $1
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

    async def remove_card(self, card_id: int, owner_id: int) -> bool:
        query = """
        DELETE FROM discord_tcg.cards
        WHERE id = $1 AND owner_id = $2
        """
        async with self.pool.acquire() as conn:
            status = await conn.execute(query, card_id, str(owner_id))
            return status == "DELETE 1"

    async def process_faucet_dividends(self, roi_divisor: int = 4):
        # Calculate dividend for each user based on sum(drating) / roi_divisor
        query = """
        WITH UserDividends AS (
            SELECT c.owner_id, SUM(p.current_drating) / $1 AS dividend
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
            await conn.execute(query, roi_divisor)
