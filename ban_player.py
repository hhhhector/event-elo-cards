"""
Ban a player and refund all card holders.

Refund priority (active cards):
  1. P2P coin sale price (coin_trades where buyer = current owner)
  2. Most recent auction winning_bid (if card was received via card trade)
  3. Specific auction winning_bid (15-min window match by winner + acquired_at)
  4. Most recent auction winning_bid for that player (fallback)
  5. Computed bank value (last resort)

Archived cards: bank value only.

Usage:
  uv run ban_player.py <player_uuid>
  uv run ban_player.py <player_uuid> --dry-run
"""

import asyncio
import argparse
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


def calculate_bank_value(rating: float) -> int:
    return int(10000 * (rating / 2200) ** 3)


async def get_refund_amount(
    conn: asyncpg.Connection,
    card_id: str,
    owner_id: str,
    player_uuid: str,
    acquired_at,
    rating: float,
    debug: bool = False,
    log=print,
) -> tuple[int, str]:
    # 1. Bought via P2P coin sale
    coin_trade = await conn.fetchrow(
        """
        SELECT coin_amount FROM discord_tcg.coin_trades
        WHERE card_id = $1 AND buyer_id = $2 AND resolved = TRUE
        ORDER BY created_at DESC LIMIT 1
        """,
        card_id, owner_id,
    )
    if coin_trade:
        amount = int(coin_trade["coin_amount"])
        return amount, f"P2P sale price ⛃ {amount:,}"

    # 2. Received via card trade — use most recent winning_bid for this player
    trade = await conn.fetchrow(
        """
        SELECT 1 FROM discord_tcg.trades
        WHERE resolved = TRUE
          AND (
            (receiver_card_id = $1 AND receiver_id = $2)
            OR (proposer_card_id = $1 AND proposer_id = $2)
          )
        LIMIT 1
        """,
        card_id, owner_id,
    )
    if trade:
        recent = await conn.fetchrow(
            """
            SELECT ac.winning_bid FROM discord_tcg.auction_cards ac
            JOIN discord_tcg.auctions a ON ac.auction_id = a.id
            WHERE ac.player_uuid = $1 AND ac.winning_bid IS NOT NULL
            ORDER BY a.closed_at DESC LIMIT 1
            """,
            player_uuid,
        )
        if recent:
            amount = int(recent["winning_bid"])
            return amount, f"most recent auction price (card-traded) ⛃ {amount:,}"
        bv = calculate_bank_value(rating)
        return bv, f"bank value fallback (card-traded, no auction record) ⛃ {bv:,}"

    # 3. Specific winning_bid via 15-min window (original auction winner, never traded)
    from datetime import timezone as _tz
    if acquired_at.tzinfo is None:
        acquired_at = acquired_at.replace(tzinfo=_tz.utc)

    if debug:
        log(f"    [debug] acquired_at: {acquired_at}")
        rows = await conn.fetch(
            """
            SELECT ac.winner_id, ac.winning_bid, a.closed_at
            FROM discord_tcg.auction_cards ac
            JOIN discord_tcg.auctions a ON ac.auction_id = a.id
            WHERE ac.player_uuid = $1 AND ac.winning_bid IS NOT NULL
            ORDER BY a.closed_at DESC
            """,
            player_uuid,
        )
        for r in rows:
            diff = (r["closed_at"] - acquired_at.replace(tzinfo=r["closed_at"].tzinfo)).total_seconds()
            log(f"    [debug] auction: winner={r['winner_id']} winning_bid={r['winning_bid']} closed_at={r['closed_at']} diff={diff:.1f}s")

    specific = await conn.fetchrow(
        """
        SELECT ac.winning_bid FROM discord_tcg.auction_cards ac
        JOIN discord_tcg.auctions a ON ac.auction_id = a.id
        WHERE ac.player_uuid = $1
          AND ac.winner_id = $2
          AND a.closed_at BETWEEN $3::timestamptz - INTERVAL '15 minutes' AND $3::timestamptz + INTERVAL '15 minutes'
          AND ac.winning_bid IS NOT NULL
        LIMIT 1
        """,
        player_uuid, owner_id, acquired_at,
    )
    if specific:
        amount = int(specific["winning_bid"])
        return amount, f"specific auction price ⛃ {amount:,}"

    # 4. Most recent winning_bid for this player (fallback)
    recent = await conn.fetchrow(
        """
        SELECT ac.winning_bid FROM discord_tcg.auction_cards ac
        JOIN discord_tcg.auctions a ON ac.auction_id = a.id
        WHERE ac.player_uuid = $1 AND ac.winning_bid IS NOT NULL
        ORDER BY a.closed_at DESC LIMIT 1
        """,
        player_uuid,
    )
    if recent:
        amount = int(recent["winning_bid"])
        return amount, f"most recent auction price (fallback) ⛃ {amount:,}"

    # 5. Bank value last resort
    bv = calculate_bank_value(rating)
    return bv, f"bank value (no auction record) ⛃ {bv:,}"


async def resolve_player(conn: asyncpg.Connection, identifier: str):
    """Resolve a UUID string or exact username to a player row. Returns None if not found."""
    import uuid as uuid_mod
    try:
        uuid_mod.UUID(identifier)
        return await conn.fetchrow(
            "SELECT uuid, current_name, current_drating, is_banned FROM event_elo.players WHERE uuid = $1",
            identifier,
        )
    except ValueError:
        # Treat as username — exact match only
        rows = await conn.fetch(
            "SELECT uuid, current_name, current_drating, is_banned FROM event_elo.players WHERE current_name = $1",
            identifier,
        )
        if len(rows) == 0:
            print(f"❌ No player found with username '{identifier}'.")
            return None
        if len(rows) > 1:
            print(f"❌ Multiple players match '{identifier}' — use UUID instead:")
            for r in rows:
                print(f"  {r['uuid']}  {r['current_name']}")
            return None
        return rows[0]


def make_logger(log_path: Path):
    """Returns a print-like function that writes to both stdout and a log file."""
    log_path.parent.mkdir(exist_ok=True)
    f = log_path.open("w", encoding="utf-8")

    def log(*args, **kwargs):
        print(*args, **kwargs)
        print(*args, **kwargs, file=f, flush=True)

    log._file = f
    return log


async def ban_player(player_uuid: str, dry_run: bool, debug: bool = False):
    pool = await asyncpg.create_pool(DATABASE_URL, statement_cache_size=0)

    try:
        async with pool.acquire() as conn:
            player = await resolve_player(conn, player_uuid)
            if not player:
                return
            player_uuid = str(player["uuid"])

            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
            prefix = "dryrun_" if dry_run else ""
            log_path = Path("ban_logs") / f"{prefix}{player['current_name']}_{ts}.txt"
            log = make_logger(log_path)

            run_prefix = "[DRY RUN] " if dry_run else ""
            log(f"\n{run_prefix}Banning {player['current_name']} ({player_uuid})")
            log(f"  Timestamp: {ts} UTC")

            if player["is_banned"]:
                log("⚠️  Already marked as banned in event_elo.players — will still process cards.")

            rating = float(player["current_drating"])
            bv = calculate_bank_value(rating)
            log(f"  Rating: {int(rating)}  |  Bank value: ⛃ {bv:,}\n")

            active_cards = await conn.fetch(
                "SELECT id, owner_id, acquired_at FROM discord_tcg.cards WHERE player_uuid = $1",
                player_uuid,
            )
            archived_cards = await conn.fetch(
                "SELECT id, owner_id FROM discord_tcg.archived_cards WHERE player_uuid = $1",
                player_uuid,
            )

            total_refunded = 0
            total_cards = len(active_cards) + len(archived_cards)

            log(f"Active cards ({len(active_cards)}):")
            if not active_cards:
                log("  (none)")

            for card in active_cards:
                refund, reason = await get_refund_amount(
                    conn,
                    str(card["id"]),
                    str(card["owner_id"]),
                    player_uuid,
                    card["acquired_at"],
                    rating,
                    debug=debug,
                    log=log,
                )
                log(f"  {str(card['id'])[:8]}… → <@{card['owner_id']}> ⛃ {refund:,}  [{reason}]")
                total_refunded += refund

                if not dry_run:
                    async with conn.transaction():
                        await conn.execute(
                            "DELETE FROM discord_tcg.cards WHERE id = $1",
                            card["id"],
                        )
                        await conn.execute(
                            "UPDATE discord_tcg.users SET coins = coins + $1, last_active = NOW() WHERE discord_id = $2",
                            refund, str(card["owner_id"]),
                        )

            log(f"\nArchived cards ({len(archived_cards)}):")
            if not archived_cards:
                log("  (none)")

            for card in archived_cards:
                log(f"  {str(card['id'])[:8]}… → <@{card['owner_id']}> ⛃ {bv:,}  [bank value]")
                total_refunded += bv

                if not dry_run:
                    async with conn.transaction():
                        await conn.execute(
                            "DELETE FROM discord_tcg.archived_cards WHERE id = $1",
                            card["id"],
                        )
                        await conn.execute(
                            "UPDATE discord_tcg.users SET coins = coins + $1, last_active = NOW() WHERE discord_id = $2",
                            bv, str(card["owner_id"]),
                        )

            if not dry_run:
                await conn.execute(
                    "UPDATE event_elo.players SET is_banned = TRUE WHERE uuid = $1",
                    player_uuid,
                )
                log(f"\n✅ Banned {player['current_name']}. Refunded ⛃ {total_refunded:,} across {total_cards} cards.")
            else:
                log(f"\n[DRY RUN] Would refund ⛃ {total_refunded:,} across {total_cards} cards. Run without --dry-run to apply.")

            log(f"\nLog saved to: {log_path}")
            log._file.close()
    finally:
        await pool.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ban a player and refund card holders.")
    parser.add_argument("player_uuid", help="Mojang UUID or exact username of the player to ban")
    parser.add_argument("--dry-run", action="store_true", help="Preview without applying any changes")
    parser.add_argument("--debug", action="store_true", help="Print raw auction data for each card")
    args = parser.parse_args()

    if not DATABASE_URL:
        print("❌ DATABASE_URL not set.")
        sys.exit(1)

    asyncio.run(ban_player(args.player_uuid, dry_run=args.dry_run, debug=args.debug))
