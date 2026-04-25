import asyncio
import random
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from src import config
from src.utils.card_generator import create_card_grid, generate_card_image
from src.utils.economy_utils import (
    calculate_bank_value,
    calculate_min_bid,
    calculate_min_increment,
)

HOURLY_AVG_MINUTES = {
    **{h: 50 for h in range(6, 12)},  # 06-12 dead
    **{h: 20 for h in range(12, 16)},  # 12-16 EU waking
    **{h: 12 for h in range(16, 20)},  # 16-20 EU peak, NA arriving
    **{h: 5 for h in range(20, 24)},  # 20-00 peak overlap
    **{h: 12 for h in range(0, 4)},  # 00-04 EU late, NA prime
    **{h: 20 for h in range(4, 6)},  # 04-06 NA winding down
}


def next_drop_delta_seconds() -> int:
    hour = datetime.now(timezone.utc).hour
    avg = HOURLY_AVG_MINUTES[hour]
    min_minutes = avg // 4
    max_minutes = avg * 2
    seconds = random.expovariate(1 / (avg * 60))
    return int(max(min_minutes * 60, min(max_minutes * 60, seconds)))


class BidModal(discord.ui.Modal):
    def __init__(self, bot, player_uuid, player_name, auction_view, balance: int):
        super().__init__(title=f"Bid on {player_name}")
        self.bot = bot
        self.player_uuid = player_uuid
        self.player_name = player_name
        self.auction_view = auction_view

        min_bid = self.auction_view.min_bids[self.player_uuid]
        min_inc = self.auction_view.min_increments[self.player_uuid]
        current_high_bid = self.auction_view.bids.get(self.player_uuid, 0)

        target = max(min_bid, current_high_bid + min_inc)

        self.bid_input = discord.ui.TextInput(
            label=f"Bid amount (balance: ⛃ {balance:,})",
            style=discord.TextStyle.short,
            placeholder=f"{target:,} or more",
            required=True,
        )
        self.add_item(self.bid_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            bid_amount = int(self.bid_input.value)
        except ValueError:
            return await interaction.response.send_message(
                "Invalid bid amount.", ephemeral=True
            )

        # Defer before acquiring the lock so the 3s ACK deadline is guaranteed
        # regardless of lock contention or DB latency in _process_bid.
        await interaction.response.defer()

        user_id = interaction.user.id

        async with self.auction_view.bid_locks[self.player_uuid]:
            if self.auction_view._closed:
                return await interaction.followup.send(
                    "This auction has ended.", ephemeral=True
                )
            await self._process_bid(interaction, user_id, bid_amount)

    async def _process_bid(
        self, interaction: discord.Interaction, user_id: int, bid_amount: int
    ):
        # Rule Enforcement: ONE card per user in this drop
        for p_uuid, (u_id, _) in self.auction_view.highest_bidders.items():
            if u_id == user_id and p_uuid != self.player_uuid:
                return await interaction.followup.send(
                    "You can only hold the highest bid on one card per drop.",
                    ephemeral=True,
                )

        roster_info = await self.bot.db.get_user_roster_info(user_id)
        if roster_info is None:
            return await interaction.followup.send(
                "You must run /register first.", ephemeral=True
            )
        coins = roster_info["coins"]
        roster_cap = roster_info["roster_cap"]

        card_count = await self.bot.db.get_card_count(user_id)
        if card_count >= roster_cap:
            return await interaction.followup.send(
                f"Your roster is full ({card_count}/{roster_cap}). Sell a card before bidding.",
                ephemeral=True,
            )

        if coins < bid_amount:
            return await interaction.followup.send(
                f"Insufficient balance. You have ⛃ {coins:,}.", ephemeral=True
            )

        min_bid = self.auction_view.min_bids[self.player_uuid]
        min_inc = self.auction_view.min_increments[self.player_uuid]
        current_high_bid = self.auction_view.bids.get(self.player_uuid, 0)

        if current_high_bid == 0:
            if bid_amount < min_bid:
                return await interaction.followup.send(
                    f"Minimum bid is {min_bid:,}.",
                    ephemeral=True,
                )
        else:
            if bid_amount < current_high_bid + min_inc:
                return await interaction.followup.send(
                    f"Bid must be at least {current_high_bid + min_inc:,}.",
                    ephemeral=True,
                )

        # Refund previous bidder (atomic: credits coins + marks bid refunded in one tx)
        previous_bidder_info = self.auction_view.highest_bidders.get(self.player_uuid)
        prev_user_id = None
        if previous_bidder_info:
            prev_user_id, prev_bid = previous_bidder_info
            prev_bid_id = self.auction_view.last_bid_ids.get(self.player_uuid)
            if prev_bid_id:
                try:
                    await self.bot.db.refund_bid(prev_bid_id)
                except Exception as e:
                    print(f"  ⚠️ refund_bid failed, falling back to non-atomic: {e}")
                    await self.bot.db.update_user_coins(prev_user_id, prev_bid)
            else:
                await self.bot.db.update_user_coins(prev_user_id, prev_bid)
            print(
                f"  ↩️ Refunded ⛃ {prev_bid:,} to user {prev_user_id} (outbid on {self.player_name})"
            )
            prev_user = self.bot.get_user(prev_user_id)
            if prev_user:
                try:
                    await prev_user.send(
                        f"Outbid on {self.player_name}. {prev_bid:,} refunded."
                    )
                except discord.HTTPException:
                    pass

        # Deduct coins
        await self.bot.db.update_user_coins(user_id, -bid_amount)
        print(f"  💸 User {user_id} bid ⛃ {bid_amount:,} on {self.player_name}")

        # Update state
        self.auction_view.bids[self.player_uuid] = bid_amount
        self.auction_view.highest_bidders[self.player_uuid] = (user_id, bid_amount)

        # Log the bid and remember its id so the next outbid can refund it atomically
        auction_card_id = self.auction_view.auction_card_ids.get(self.player_uuid)
        if auction_card_id:
            try:
                new_bid_id = await self.bot.db.log_bid(
                    auction_card_id, user_id, bid_amount
                )
                self.auction_view.last_bid_ids[self.player_uuid] = new_bid_id
            except Exception as e:
                print(f"  ⚠️ Failed to log bid: {e}")
                self.auction_view.last_bid_ids[self.player_uuid] = None

        # Update button label and style
        next_min = bid_amount + min_inc
        for item in self.auction_view.children:
            if (
                isinstance(item, discord.ui.Button)
                and item.custom_id == f"bid_{self.player_uuid}"
            ):
                item.label = f"{self.player_name} - ⛃ {next_min:,}"
                item.style = discord.ButtonStyle.primary
                break

        # Edit the auction message directly (bot webhook, not via interaction token —
        # avoids Discord 3s interaction-token expiry during slow DB paths).
        if self.auction_view.message:
            try:
                await self.auction_view.message.edit(view=self.auction_view)
            except discord.HTTPException as e:
                print(f"  ⚠️ Failed to refresh auction view: {e}")

            announcement = f"<@{user_id}> bid ⛃ {bid_amount:,} on **{self.player_name}**. Minimum bid is now ⛃ {next_min:,}."
            if prev_user_id and prev_user_id != user_id:
                announcement += f" (outbid <@{prev_user_id}>)"
            await self.auction_view.message.channel.send(announcement)


class AuctionView(discord.ui.View):
    def __init__(
        self,
        bot,
        players,
        duration_seconds: int,
        auction_id=None,
        auction_card_ids=None,
    ):
        super().__init__(timeout=duration_seconds)
        self.bot = bot
        self.players = players
        self.bids = {p["uuid"]: 0 for p in players}
        self.min_bids = {}
        self.min_increments = {}
        self.highest_bidders = {}  # player_uuid -> (user_id, bid_amount)
        self.bid_locks = {p["uuid"]: asyncio.Lock() for p in players}
        self.message = None
        self.deadline = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
        self._closed = False
        self.auction_id = auction_id
        self.auction_card_ids = auction_card_ids or {}
        self.last_bid_ids = {}  # player_uuid -> bid_id (for atomic refund on outbid)

        for p in players:
            rating = float(p["current_drating"])
            rank = p.get("current_rank", "N/A")
            bv = calculate_bank_value(rating)
            mb = calculate_min_bid(rating, rank)
            mi = calculate_min_increment(bv)
            self.min_bids[p["uuid"]] = mb
            self.min_increments[p["uuid"]] = mi

            btn = discord.ui.Button(
                label=f"{p['current_name']} - ⛃ {mb:,}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"bid_{p['uuid']}",
            )
            btn.callback = self.make_callback(p["uuid"], p["current_name"])
            self.add_item(btn)

    def make_callback(self, player_uuid, player_name):
        async def callback(interaction: discord.Interaction):
            if datetime.now(timezone.utc) > self.deadline:
                return await interaction.response.send_message(
                    "This auction has ended.", ephemeral=True
                )
            balance = await self.bot.db.get_user_coins(interaction.user.id) or 0
            modal = BidModal(
                self.bot, player_uuid, player_name, self, int(float(balance))
            )
            await interaction.response.send_modal(modal)

        return callback

    async def on_timeout(self):
        if self._closed:
            return
        self._closed = True
        # Drain every per-card lock so any in-flight BidModal.on_submit finishes
        # (and any modal that arrives after this point will see _closed=True and reject).
        for lock in self.bid_locks.values():
            async with lock:
                pass
        print(
            f"⏰ Auction timed out. Bids placed: {len(self.highest_bidders)}/{len(self.players)} cards."
        )
        try:
            for child in self.children:
                child.disabled = True

            winners_summary = []
            for player_uuid, (user_id, bid_amount) in self.highest_bidders.items():
                player_name = next(
                    (
                        p["current_name"]
                        for p in self.players
                        if p["uuid"] == player_uuid
                    ),
                    "Unknown",
                )
                print(
                    f"  → Awarding {player_name} to user {user_id} for ⛃ {bid_amount:,}"
                )
                try:
                    await self.bot.db.add_card_to_user(user_id, player_uuid)
                    winners_summary.append(
                        f"<@{user_id}> won {player_name} for ⛃ {bid_amount:,}"
                    )
                    print(f"    ✅ Card awarded.")
                except Exception as e:
                    print(f"    ❌ Failed to award card: {e}")

            if self.message:
                try:
                    await self.message.edit(view=self)
                    print("  ✅ Auction buttons disabled.")
                except discord.HTTPException as e:
                    print(f"  ⚠️ Failed to disable auction buttons: {e}")
                try:
                    if winners_summary:
                        reply_text = "**Auction Closed**\n" + "\n".join(winners_summary)
                    else:
                        reply_text = "**Auction Closed**\nNo bids placed."
                    await self.message.reply(reply_text)
                    print("  ✅ Auction close message sent.")
                except discord.HTTPException as e:
                    print(f"  ⚠️ Failed to send auction close message: {e}")

            # Finalize logs
            if self.auction_id:
                for p in self.players:
                    card_id = self.auction_card_ids.get(p["uuid"])
                    if not card_id:
                        continue
                    bidder = self.highest_bidders.get(p["uuid"])
                    winner_id, winning_bid = (
                        (bidder[0], bidder[1]) if bidder else (None, None)
                    )
                    try:
                        await self.bot.db.finalize_auction_card(
                            card_id, winner_id, winning_bid
                        )
                    except Exception as e:
                        print(f"  ⚠️ Failed to finalize auction_card log: {e}")
                try:
                    await self.bot.db.finalize_auction(self.auction_id)
                except Exception as e:
                    print(f"  ⚠️ Failed to finalize auction log: {e}")
        except Exception as e:
            print(f"  ❌ Unexpected error during auction close: {e}")
        finally:
            try:
                await self.bot.db.set_auction_active(False)
                print("🔒 is_active reset to False.")
            except Exception as e:
                print(f"CRITICAL: Failed to reset is_active: {e}")
            try:
                delta = next_drop_delta_seconds()
                next_ts = datetime.now(timezone.utc) + timedelta(seconds=delta)
                await self.bot.db.set_next_drop_timestamp(next_ts)
                print(f"🕒 Next drop scheduled in {delta // 60}m.")
            except Exception as e:
                print(f"❌ Failed to schedule next drop: {e}")


class Auction(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.drop_loop.start()

    def cog_unload(self):
        self.drop_loop.cancel()

    @app_commands.command(
        name="pingme", description="Toggle auction drop notifications"
    )
    async def pingme(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        drop_channel = self.bot.get_channel(config.DROP_CHANNEL_ID)
        if drop_channel is None:
            return await interaction.followup.send(
                "Drop channel not available.", ephemeral=True
            )
        guild = drop_channel.guild
        role = guild.get_role(config.AUCTION_PING_ROLE_ID)
        if role is None:
            return await interaction.followup.send(
                "Notification role not configured.", ephemeral=True
            )
        try:
            member = await guild.fetch_member(interaction.user.id)
        except discord.NotFound:
            return await interaction.followup.send(
                "You must be a member of the server.", ephemeral=True
            )
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="User disabled drop pings")
                return await interaction.followup.send(
                    "Drop pings disabled.", ephemeral=True
                )
            else:
                await member.add_roles(role, reason="User enabled drop pings")
                return await interaction.followup.send(
                    "You'll be pinged for drops.", ephemeral=True
                )
        except discord.Forbidden:
            return await interaction.followup.send(
                "I don't have permission to manage that role. Check role hierarchy and Manage Roles permission.",
                ephemeral=True,
            )

    @tasks.loop(minutes=1)
    async def drop_loop(self):
        if getattr(self.bot, "db", None) is None:
            return
        state = await self.bot.db.get_system_state()
        if not state:
            return

        now = datetime.now(timezone.utc)
        is_active = state["is_active"]
        next_ts = state["next_drop_timestamp"]

        if is_active:
            return

        if next_ts is None:
            # First run — schedule from now
            delta = next_drop_delta_seconds()
            await self.bot.db.set_next_drop_timestamp(now + timedelta(seconds=delta))
            return

        next_ts_utc = next_ts.replace(tzinfo=timezone.utc)

        if next_ts_utc < now - timedelta(minutes=1):
            # Stale (maintenance window) — reschedule from now, don't fire
            delta = next_drop_delta_seconds()
            await self.bot.db.set_next_drop_timestamp(now + timedelta(seconds=delta))
            return

        if next_ts_utc <= now:
            await self._fire_auto_drop()

    @drop_loop.error
    async def on_drop_loop_error(self, error):
        print(f"❌ Drop loop crashed: {error}. Restarting loop.")
        await self.bot.db.set_auction_active(False)
        self.drop_loop.restart()

    @drop_loop.before_loop
    async def before_drop_loop(self):
        await self.bot.wait_until_ready()
        # Reset stale is_active in case the bot was killed mid-auction.
        # The View is gone so the auction is unrecoverable anyway.
        await self.bot.db.set_auction_active(False)
        print("✅ Drop loop started.")

    async def _send_drop(self, players, title):
        print(f"  Generating images for {len(players)} cards...")
        player_images = []
        for p in players:
            img_buffer = await generate_card_image(dict(p))
            player_images.append(img_buffer)
            print(f"    ✅ Image generated: {p['current_name']}")

        combined_image = await create_card_grid(player_images, cols=4)
        file = discord.File(fp=combined_image, filename="drop.png")
        duration_seconds = random.randint(7 * 60, 15 * 60)

        auction_id = None
        auction_card_ids = {}
        try:
            auction_id = await self.bot.db.create_auction(duration_seconds)
            for p in players:
                rating = float(p["current_drating"])
                rank_raw = p.get("current_rank")
                rank = int(rank_raw) if rank_raw is not None else None
                bv = calculate_bank_value(rating)
                mb = calculate_min_bid(
                    rating, rank_raw if rank_raw is not None else "N/A"
                )
                mi = calculate_min_increment(bv)
                card_id = await self.bot.db.create_auction_card(
                    auction_id,
                    p["uuid"],
                    rating,
                    rank,
                    bv,
                    mb,
                    mi,
                )
                auction_card_ids[p["uuid"]] = card_id
        except Exception as e:
            print(f"  ⚠️ Failed to log auction to DB: {e}")
            auction_id = None
            auction_card_ids = {}

        view = AuctionView(
            self.bot, players, duration_seconds, auction_id, auction_card_ids
        )
        content = f"<@&{config.AUCTION_PING_ROLE_ID}> **{title}**\nBid below. One active bid per drop. Bank value and yield shown top-right of each card."

        channel = self.bot.get_channel(config.DROP_CHANNEL_ID)
        if not channel:
            print(f"  ❌ Drop channel {config.DROP_CHANNEL_ID} not found.")
            return
        msg = await channel.send(
            content=content,
            file=file,
            view=view,
            allowed_mentions=discord.AllowedMentions(roles=True),
        )
        print(
            f"  ✅ Drop sent to channel {config.DROP_CHANNEL_ID}. Auction closes in {duration_seconds // 60}m {duration_seconds % 60}s."
        )
        view.message = msg
        asyncio.create_task(self._force_close_auction(view, seconds=duration_seconds))

    async def _force_close_auction(self, view: AuctionView, seconds: int):
        await asyncio.sleep(seconds)
        await view.on_timeout()

    async def _fire_auto_drop(self):
        players = await self.bot.db.get_random_unbanned_players(limit=8)
        if not players:
            print("⚠️ Auto drop skipped: no eligible players found.")
            return

        await self.bot.db.set_auction_active(True)
        print(f"🃏 Auto drop fired ({len(players)} cards).")
        try:
            await self._send_drop(players, "MARKET DROP")
        except Exception as e:
            print(f"❌ Drop failed during send: {e}. Resetting is_active.")
            await self.bot.db.set_auction_active(False)
            raise


async def setup(bot):
    await bot.add_cog(Auction(bot))
