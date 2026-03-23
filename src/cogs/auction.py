import discord
from discord import app_commands
from discord.ext import commands

from src import config
from src.utils.card_generator import create_card_grid, generate_card_image
from src.utils.economy_utils import (
    calculate_bank_value,
    calculate_min_bid,
    calculate_min_increment,
    calculate_yield_value,
)


class BidModal(discord.ui.Modal):
    def __init__(self, bot, player_uuid, player_name, auction_view):
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
            label="Bid amount",
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
        for u_id, p_uuid in self.auction_view.highest_bidders.values():
            if u_id == user_id and p_uuid != self.player_uuid:
                return await interaction.response.send_message(
                    "You can only hold the highest bid on one card per drop.",
                    ephemeral=True,
                )

        coins = await self.bot.db.get_user_coins(user_id)
        if coins is None:
            return await interaction.response.send_message(
                "You must run /register first.", ephemeral=True
            )
        if coins < bid_amount:
            return await interaction.response.send_message(
                f"Insufficient balance. You have {coins:,}.", ephemeral=True
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
        for item in self.auction_view.children:
            if (
                isinstance(item, discord.ui.Button)
                and item.custom_id == f"bid_{self.player_uuid}"
            ):
                next_bid = bid_amount + min_inc
                item.label = f"{self.player_name} - ⛃ {next_bid:,}"
                item.style = discord.ButtonStyle.primary
                break

        await interaction.response.edit_message(view=self.auction_view)
        
        # Public announcement
        if self.auction_view.message:
            await self.auction_view.message.channel.send(
                f"<@{user_id}> bid ⛃ {bid_amount:,} on **{self.player_name}**"
            )


class AuctionView(discord.ui.View):
    def __init__(self, bot, players):
        super().__init__(timeout=300)
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
            modal = BidModal(self.bot, player_uuid, player_name, self)
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
            winners_summary.append(f"<@{user_id}> won {player_name} for {bid_amount:,}")

        if self.message:
            try:
                await self.message.edit(view=self)
                if winners_summary:
                    reply_text = "**Auction Closed**\n" + "\n".join(winners_summary)
                else:
                    reply_text = "**Auction Closed**\nNo bids placed."
                await self.message.reply(reply_text)
            except discord.HTTPException:
                pass


class Auction(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _process_drop(self, interaction, players, title):
        if not players:
            return await interaction.followup.send("No eligible players found.")

        # Fetch stats and generate images
        player_images = []
        for p in players:
            img_buffer = await generate_card_image(dict(p))
            player_images.append(img_buffer)

        # Stitch them together into a 3-column grid
        combined_image = await create_card_grid(player_images, cols=3)
        file = discord.File(fp=combined_image, filename="drop.png")

        view = AuctionView(self.bot, players)

        # Minimalist description
        description = f"**{title}**\nBid below. One active bid per drop."

        msg = await interaction.followup.send(content=description, file=file, view=view)
        view.message = msg

    @app_commands.command(name="drop", description="Trigger a card drop")
    @app_commands.checks.has_permissions(administrator=True)
    async def drop_cards(self, interaction: discord.Interaction):
        if getattr(self.bot, "db", None) is None:
            return await interaction.response.send_message(
                "Database not connected.", ephemeral=True
            )

        await interaction.response.defer()
        players = await self.bot.db.get_random_unbanned_players(limit=3)
        await self._process_drop(interaction, players, "MARKET DROP")

    @app_commands.command(
        name="fulldrop",
        description="DEBUG: Drops one card from every rarity tier (X, S, A, B, C, D)",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def full_drop(self, interaction: discord.Interaction):
        if getattr(self.bot, "db", None) is None:
            return await interaction.response.send_message(
                "Database not connected.", ephemeral=True
            )

        await interaction.response.defer()

        # Rarity Brackets
        tiers = [(1, 10), (11, 100), (101, 250), (251, 500), (501, 1000), (1001, None)]
        players = []
        for low, high in tiers:
            p = await self.bot.db.get_random_player_in_rank_range(low, high)
            if p:
                players.append(p)

        await self._process_drop(interaction, players, "FULL TIER DEBUG DROP")


async def setup(bot):
    await bot.add_cog(Auction(bot))
