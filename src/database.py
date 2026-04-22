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
        WHERE is_banned = FALSE AND current_drating IS NOT NULL
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
        SELECT c.id as card_id, c.player_uuid, c.acquired_at, p.current_name, p.current_drating, p.current_rank
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

    async def get_stats_message_id(self) -> Optional[int]:
        query = "SELECT stats_message_id FROM discord_tcg.system_state WHERE id = 1"
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query)

    async def set_stats_message_id(self, message_id: int) -> None:
        query = "UPDATE discord_tcg.system_state SET stats_message_id = $1 WHERE id = 1"
        async with self.pool.acquire() as conn:
            await conn.execute(query, message_id)

    async def get_leaderboard_coins(self, limit: int = 10) -> List[asyncpg.Record]:
        query = """
        SELECT discord_id, coins
        FROM discord_tcg.users
        ORDER BY coins DESC
        LIMIT $1
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, limit)

    async def get_leaderboard_portfolio(self, limit: int = 10) -> List[asyncpg.Record]:
        query = """
        SELECT c.owner_id AS discord_id,
               SUM(10000.0 * POWER(p.current_drating / 2200.0, 3)) AS portfolio
        FROM discord_tcg.cards c
        JOIN event_elo.players p ON c.player_uuid = p.uuid
        WHERE p.is_banned = FALSE
        GROUP BY c.owner_id
        ORDER BY portfolio DESC
        LIMIT $1
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, limit)

    async def get_leaderboard_combined(self, limit: int = 10) -> List[asyncpg.Record]:
        query = """
        SELECT u.discord_id,
               u.coins + COALESCE(SUM(10000.0 * POWER(p.current_drating / 2200.0, 3)), 0) AS combined
        FROM discord_tcg.users u
        LEFT JOIN discord_tcg.cards c ON c.owner_id = u.discord_id
        LEFT JOIN event_elo.players p ON c.player_uuid = p.uuid AND p.is_banned = FALSE
        GROUP BY u.discord_id, u.coins
        ORDER BY combined DESC
        LIMIT $1
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, limit)

    async def get_economy_stats(self) -> Optional[asyncpg.Record]:
        query = """
        SELECT
            (SELECT COUNT(*) FROM discord_tcg.users) AS total_users,
            (SELECT COALESCE(SUM(coins), 0) FROM discord_tcg.users) AS total_coins,
            (SELECT COUNT(*) FROM discord_tcg.cards) AS total_cards,
            (SELECT COALESCE(SUM(
                10000.0 * POWER(p.current_drating / 2200.0, 3) *
                CASE
                    WHEN p.current_rank IS NULL       THEN 1.0/7.0
                    WHEN p.current_rank <= 10         THEN 0.30
                    WHEN p.current_rank <= 100        THEN 0.22
                    WHEN p.current_rank <= 250        THEN 0.18
                    WHEN p.current_rank <= 500        THEN 0.15
                    WHEN p.current_rank <= 1000       THEN 1.0/7.0
                    ELSE 1.0/7.0
                END
             ), 0)
             FROM discord_tcg.cards c
             JOIN event_elo.players p ON c.player_uuid = p.uuid
             WHERE p.is_banned = FALSE) AS total_daily_yield,
            (SELECT COUNT(*) FROM discord_tcg.cards c JOIN event_elo.players p ON c.player_uuid = p.uuid WHERE p.is_banned = FALSE AND p.current_rank <= 10) AS cards_x,
            (SELECT COUNT(*) FROM discord_tcg.cards c JOIN event_elo.players p ON c.player_uuid = p.uuid WHERE p.is_banned = FALSE AND p.current_rank BETWEEN 11 AND 100) AS cards_s,
            (SELECT COUNT(*) FROM discord_tcg.cards c JOIN event_elo.players p ON c.player_uuid = p.uuid WHERE p.is_banned = FALSE AND p.current_rank BETWEEN 101 AND 250) AS cards_a,
            (SELECT COUNT(*) FROM discord_tcg.cards c JOIN event_elo.players p ON c.player_uuid = p.uuid WHERE p.is_banned = FALSE AND p.current_rank BETWEEN 251 AND 500) AS cards_b,
            (SELECT COUNT(*) FROM discord_tcg.cards c JOIN event_elo.players p ON c.player_uuid = p.uuid WHERE p.is_banned = FALSE AND p.current_rank BETWEEN 501 AND 1000) AS cards_c,
            (SELECT COUNT(*) FROM discord_tcg.cards c JOIN event_elo.players p ON c.player_uuid = p.uuid WHERE p.is_banned = FALSE AND p.current_rank > 1000) AS cards_d
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchrow(query)

    async def claim_dividend_payout(self, expected_ts, next_ts) -> bool:
        """Atomically claim the dividend payout by updating the timestamp only if it matches.
        Returns True if this bot instance won the race, False if another already claimed it."""
        query = """
        UPDATE discord_tcg.system_state
        SET next_dividend_timestamp = $1
        WHERE id = 1 AND next_dividend_timestamp = $2
        """
        async with self.pool.acquire() as conn:
            status = await conn.execute(query, next_ts, expected_ts)
            return status == "UPDATE 1"

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
        # Tiered yield rates per rarity. Keep in sync with YIELD_RATES in
        # src/utils/economy_utils.py.
        query = """
        WITH UserDividends AS (
            SELECT
                c.owner_id,
                SUM(
                    10000.0 * POWER(p.current_drating / 2200.0, 3) *
                    CASE
                        WHEN p.current_rank IS NULL       THEN 1.0/7.0
                        WHEN p.current_rank <= 10         THEN 0.30
                        WHEN p.current_rank <= 100        THEN 0.22
                        WHEN p.current_rank <= 250        THEN 0.18
                        WHEN p.current_rank <= 500        THEN 0.15
                        WHEN p.current_rank <= 1000       THEN 1.0/7.0
                        ELSE 1.0/7.0
                    END
                )::INT AS dividend
            FROM discord_tcg.cards c
            JOIN event_elo.players p ON c.player_uuid = p.uuid
            WHERE p.is_banned = FALSE
            GROUP BY c.owner_id
        ),
        Updated AS (
            UPDATE discord_tcg.users u
            SET coins = u.coins + ud.dividend
            FROM UserDividends ud
            WHERE u.discord_id = ud.owner_id
            RETURNING ud.owner_id, ud.dividend
        )
        INSERT INTO discord_tcg.dividend_payouts (user_id, amount)
        SELECT owner_id, dividend FROM Updated WHERE dividend > 0;
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query)

    # --- Market logging ---

    async def create_auction(self, duration_seconds: int) -> str:
        query = """
        INSERT INTO discord_tcg.auctions (duration_seconds)
        VALUES ($1)
        RETURNING id
        """
        async with self.pool.acquire() as conn:
            return str(await conn.fetchval(query, duration_seconds))

    async def create_auction_card(
        self,
        auction_id: str,
        player_uuid: str,
        rating: float,
        rank: Optional[int],
        bank_value: int,
        min_bid: int,
        min_increment: int,
    ) -> str:
        query = """
        INSERT INTO discord_tcg.auction_cards
            (auction_id, player_uuid, rating, rank, bank_value, min_bid, min_increment)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
        """
        async with self.pool.acquire() as conn:
            return str(await conn.fetchval(
                query, auction_id, player_uuid, rating, rank, bank_value, min_bid, min_increment
            ))

    async def log_bid(self, auction_card_id: str, user_id: int, amount: int) -> str:
        query = """
        INSERT INTO discord_tcg.bids (auction_card_id, user_id, amount)
        VALUES ($1, $2, $3)
        RETURNING id
        """
        async with self.pool.acquire() as conn:
            return str(await conn.fetchval(query, auction_card_id, str(user_id), amount))

    async def refund_bid(self, bid_id: str) -> Optional[int]:
        """Atomically mark a bid as refunded and credit its amount back to the bidder.
        Returns the new coin balance, or None if the bid was already refunded / not found."""
        query = """
        WITH b AS (
            UPDATE discord_tcg.bids
            SET was_refunded = TRUE, refunded_at = NOW()
            WHERE id = $1 AND was_refunded = FALSE
            RETURNING user_id, amount
        )
        UPDATE discord_tcg.users u
        SET coins = u.coins + b.amount, last_active = CURRENT_TIMESTAMP
        FROM b
        WHERE u.discord_id = b.user_id
        RETURNING u.coins
        """
        async with self.pool.acquire() as conn:
            return await conn.fetchval(query, bid_id)

    async def finalize_auction_card(
        self,
        auction_card_id: str,
        winner_id: Optional[int],
        winning_bid: Optional[int],
    ) -> None:
        winner_str = str(winner_id) if winner_id is not None else None
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE discord_tcg.auction_cards
                    SET winner_id = $2,
                        winning_bid = $3,
                        bid_count = (SELECT COUNT(*) FROM discord_tcg.bids WHERE auction_card_id = $1)
                    WHERE id = $1
                    """,
                    auction_card_id, winner_str, winning_bid,
                )
                if winner_str is not None and winning_bid is not None:
                    await conn.execute(
                        """
                        UPDATE discord_tcg.bids
                        SET was_winner = TRUE
                        WHERE id = (
                            SELECT id FROM discord_tcg.bids
                            WHERE auction_card_id = $1 AND user_id = $2 AND amount = $3
                            ORDER BY placed_at DESC
                            LIMIT 1
                        )
                        """,
                        auction_card_id, winner_str, winning_bid,
                    )

    async def finalize_auction(self, auction_id: str) -> None:
        query = """
        UPDATE discord_tcg.auctions
        SET closed_at = NOW()
        WHERE id = $1
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, auction_id)

    async def log_sale(
        self,
        user_id: int,
        player_uuid: str,
        rating: float,
        rank: Optional[int],
        sale_price: int,
        held_seconds: int,
    ) -> None:
        query = """
        INSERT INTO discord_tcg.sales (user_id, player_uuid, rating, rank, sale_price, held_seconds)
        VALUES ($1, $2, $3, $4, $5, $6)
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query, str(user_id), player_uuid, rating, rank, sale_price, held_seconds)

    # --- Market KPI snapshots ---

    async def insert_kpi_snapshots(self) -> None:
        """Compute mean winning-bid / bank-value per rarity over the last 6h
        of closed auctions and insert one snapshot row per rarity that has data.
        (Column name `median_wb_over_bv` is legacy — value is now a mean.)"""
        query = """
        WITH closed_cards AS (
            SELECT
                ac.winning_bid::numeric / NULLIF(ac.bank_value, 0)::numeric AS wb_over_bv,
                CASE
                    WHEN ac.rank IS NULL THEN 'D'
                    WHEN ac.rank <= 10 THEN 'X'
                    WHEN ac.rank <= 100 THEN 'S'
                    WHEN ac.rank <= 250 THEN 'A'
                    WHEN ac.rank <= 500 THEN 'B'
                    WHEN ac.rank <= 1000 THEN 'C'
                    ELSE 'D'
                END AS rarity
            FROM discord_tcg.auction_cards ac
            JOIN discord_tcg.auctions a ON ac.auction_id = a.id
            WHERE a.closed_at >= NOW() - INTERVAL '6 hours'
              AND ac.winning_bid IS NOT NULL
              AND ac.bank_value > 0
        )
        INSERT INTO discord_tcg.market_kpi_snapshots (rarity, median_wb_over_bv, sample_size)
        SELECT rarity, AVG(wb_over_bv), COUNT(*)
        FROM closed_cards
        GROUP BY rarity
        """
        async with self.pool.acquire() as conn:
            await conn.execute(query)

    async def get_kpi_snapshots(self, hours: int = 24) -> List[asyncpg.Record]:
        query = """
        SELECT taken_at, rarity, median_wb_over_bv, sample_size
        FROM discord_tcg.market_kpi_snapshots
        WHERE taken_at >= NOW() - INTERVAL '1 hour' * $1
        ORDER BY taken_at ASC
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, hours)

    async def get_winning_bid_scatter(self, hours: int = 24) -> List[asyncpg.Record]:
        """One row per closed auction with a winner in the window."""
        query = """
        SELECT
            a.closed_at,
            (ac.winning_bid::numeric / ac.bank_value::numeric) AS wb_over_bv,
            CASE
                WHEN ac.rank IS NULL THEN 'D'
                WHEN ac.rank <= 10 THEN 'X'
                WHEN ac.rank <= 100 THEN 'S'
                WHEN ac.rank <= 250 THEN 'A'
                WHEN ac.rank <= 500 THEN 'B'
                WHEN ac.rank <= 1000 THEN 'C'
                ELSE 'D'
            END AS rarity
        FROM discord_tcg.auction_cards ac
        JOIN discord_tcg.auctions a ON ac.auction_id = a.id
        WHERE a.closed_at >= NOW() - INTERVAL '1 hour' * $1
          AND ac.winning_bid IS NOT NULL
          AND ac.bank_value > 0
        ORDER BY a.closed_at ASC
        """
        async with self.pool.acquire() as conn:
            return await conn.fetch(query, hours)
