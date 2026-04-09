import random
import math
from datetime import datetime, timezone, timedelta

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


def next_drop_delta_seconds(avg_minutes: int = 60, min_minutes: int = 15, max_minutes: int = 120) -> int:
    seconds = random.expovariate(1 / (avg_minutes * 60))
    return int(max(min_minutes * 60, min(max_minutes * 60, seconds)))


def poisson_card_count(avg: int = 4, minimum: int = 1, maximum: int = 8) -> int:
    count = 0
    L = math.exp(-avg)
    p = 1.0
    while p > L:
        p *= random.random()
        count += 1
    return max(minimum, min(maximum, count - 1))


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

        user_id = interaction.user.id

        # Rule Enforcement: ONE card per user in this drop
        for p_uuid, (u_id, _) in self.auction_view.highest_bidders.items():
            if u_id == user_id and p_uuid != self.player_uuid:
                return await interaction.response.send_message(
                    "You can only hold the highest bid on one card per drop.",
                    ephemeral=True,
                )

        roster_info = await self.bot.db.get_user_roster_info(user_id)
        if roster_info is None:
            return await interaction.response.send_message(
                "You must run /register first.", ephemeral=True
            )
        coins = roster_info["coins"]
        roster_cap = roster_info["roster_cap"]

        card_count = await self.bot.db.get_card_count(user_id)
        if card_count >= roster_cap:
            return await interaction.response.send_message(
                f"Your roster is full ({card_count}/{roster_cap}). Sell a card before bidding.",
                ephemeral=True,
            )

        if coins < bid_amount:
            return await interaction.response.send_message(
                f"Insufficient balance. You have ⛃ {coins:,}.", ephemeral=True
            )

        min_bid = self.auction_view.min_bids[self.player_uuid]
        min_inc = self.auction_view.min_increments[self.player_uuid]
        current_high_bid = self.auction_view.bids.get(self.player_uuid, 0)

        if current_high_bid == 0:
            if bid_amount < min_bid:
                return await interaction.response.send_message(
                    f"Minimum bid is {min_bid:,}.",
                    ephemeral=True,
                )
        else:
            if bid_amount < current_high_bid + min_inc:
                return await interaction.response.send_message(
                    f"Bid must be at least {current_high_bid + min_inc:,}.",
                    ephemeral=True,
                )

        # Refund previous bidder
        previous_bidder_info = self.auction_view.highest_bidders.get(self.player_uuid)
        if previous_bidder_info:
            prev_user_id, prev_bid = previous_bidder_info
            await self.bot.db.update_user_coins(prev_user_id, prev_bid)
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

        # Update state
        self.auction_view.bids[self.player_uuid] = bid_amount
        self.auction_view.highest_bidders[self.player_uuid] = (user_id, bid_amount)

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

        await interaction.response.edit_message(view=self.auction_view)

        # Public announcement
        if self.auction_view.message:
            await self.auction_view.message.channel.send(
                f"<@{user_id}> bid ⛃ {bid_amount:,} on **{self.player_name}**. Minimum bid is now ⛃ {next_min:,}."
            )


class AuctionView(discord.ui.View):
    def __init__(self, bot, players):
        super().__init__(timeout=600)
        self.bot = bot
        self.players = players
        self.bids = {p["uuid"]: 0 for p in players}
        self.min_bids = {}
        self.min_increments = {}
        self.highest_bidders = {}  # player_uuid -> (user_id, bid_amount)
        self.message = None

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
            balance = await self.bot.db.get_user_coins(interaction.user.id) or 0
            modal = BidModal(self.bot, player_uuid, player_name, self, int(float(balance)))
            await interaction.response.send_modal(modal)

        return callback

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True

        winners_summary = []
        for player_uuid, (user_id, bid_amount) in self.highest_bidders.items():
            await self.bot.db.add_card_to_user(user_id, player_uuid)
            player_name = next(
                (p["current_name"] for p in self.players if p["uuid"] == player_uuid),
                "Unknown",
            )
            winners_summary.append(f"<@{user_id}> won {player_name} for ⛃ {bid_amount:,}")

        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException as e:
                print(f"Failed to disable auction buttons: {e}")
            try:
                if winners_summary:
                    reply_text = "**Auction Closed**\n" + "\n".join(winners_summary)
                else:
                    reply_text = "**Auction Closed**\nNo bids placed."
                await self.message.reply(reply_text)
            except discord.HTTPException as e:
                print(f"Failed to send auction close message: {e}")

        await self.bot.db.set_auction_active(False)


class Auction(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.drop_loop.start()

    def cog_unload(self):
        self.drop_loop.cancel()

    @tasks.loop(minutes=1)
    async def drop_loop(self):
        if getattr(self.bot, 'db', None) is None:
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

    @drop_loop.before_loop
    async def before_drop_loop(self):
        await self.bot.wait_until_ready()
        # Reset stale is_active in case the bot was killed mid-auction.
        # The View is gone so the auction is unrecoverable anyway.
        await self.bot.db.set_auction_active(False)
        print("✅ Drop loop started.")

    async def _send_drop(self, players, title, *, interaction=None):
        """Send a drop to a channel or as an interaction followup."""
        player_images = []
        for p in players:
            img_buffer = await generate_card_image(dict(p))
            player_images.append(img_buffer)

        combined_image = await create_card_grid(player_images, cols=3)
        file = discord.File(fp=combined_image, filename="drop.png")
        view = AuctionView(self.bot, players)
        content = f"**{title}**\nBid below. One active bid per drop."

        if interaction:
            msg = await interaction.followup.send(content=content, file=file, view=view)
        else:
            channel = self.bot.get_channel(config.DROP_CHANNEL_ID)
            if not channel:
                return
            msg = await channel.send(content=content, file=file, view=view)

        view.message = msg

    async def _fire_auto_drop(self):
        count = poisson_card_count()
        players = await self.bot.db.get_random_unbanned_players(limit=count)
        if not players:
            return

        await self.bot.db.set_auction_active(True)
        delta = next_drop_delta_seconds()
        await self.bot.db.set_next_drop_timestamp(datetime.now(timezone.utc) + timedelta(seconds=delta))
        await self._send_drop(players, "MARKET DROP")

    async def _check_and_block_if_active(self, interaction) -> bool:
        """Returns True if blocked (auction active), False if clear to proceed."""
        state = await self.bot.db.get_system_state()
        if state and state["is_active"]:
            await interaction.response.send_message(
                "An auction is already in progress.", ephemeral=True
            )
            return True
        return False

    @app_commands.command(name="drop", description="Trigger a card drop")
    @app_commands.checks.has_permissions(administrator=True)
    async def drop_cards(self, interaction: discord.Interaction):
        if await self._check_and_block_if_active(interaction):
            return
        await interaction.response.defer()
        await self.bot.db.set_auction_active(True)
        players = await self.bot.db.get_random_unbanned_players(limit=3)
        if not players:
            return await interaction.followup.send("No eligible players found.")
        await self._send_drop(players, "MARKET DROP", interaction=interaction)

    @app_commands.command(
        name="fulldrop",
        description="DEBUG: Drops one card from every rarity tier (X, S, A, B, C, D)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def full_drop(self, interaction: discord.Interaction):
        if await self._check_and_block_if_active(interaction):
            return
        await interaction.response.defer()
        await self.bot.db.set_auction_active(True)
        tiers = [(1, 10), (11, 100), (101, 250), (251, 500), (501, 1000), (1001, None)]
        players = []
        for low, high in tiers:
            p = await self.bot.db.get_random_player_in_rank_range(low, high)
            if p:
                players.append(p)
        if not players:
            return await interaction.followup.send("No eligible players found.")
        await self._send_drop(players, "FULL TIER DEBUG DROP", interaction=interaction)


async def setup(bot):
    await bot.add_cog(Auction(bot))
