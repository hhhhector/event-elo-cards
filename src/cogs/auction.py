import discord
from discord import app_commands
from discord.ext import commands
from src import config

class BidModal(discord.ui.Modal):
    def __init__(self, bot, player_uuid, player_name, auction_view):
        super().__init__(title=f"Bid on {player_name}")
        self.bot = bot
        self.player_uuid = player_uuid
        self.player_name = player_name
        self.auction_view = auction_view

        self.bid_input = discord.ui.TextInput(
            label="Bid Amount",
            style=discord.TextStyle.short,
            placeholder="Enter your bid in coins...",
            required=True
        )
        self.add_item(self.bid_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            bid_amount = int(self.bid_input.value)
        except ValueError:
            return await interaction.response.send_message("❌ Invalid bid amount.", ephemeral=True)

        user_id = interaction.user.id
        
        # Rule Enforcement: ONE card per user in this drop
        for u_id, p_uuid in self.auction_view.highest_bidders.values():
            if u_id == user_id and p_uuid != self.player_uuid:
                return await interaction.response.send_message("❌ You can only hold the highest bid on ONE card per drop!", ephemeral=True)

        coins = await self.bot.db.get_user_coins(user_id)
        if coins < bid_amount:
            return await interaction.response.send_message(f"❌ You don't have enough coins. Balance: {coins}", ephemeral=True)

        current_high_bid = self.auction_view.bids.get(self.player_uuid, 0)
        if bid_amount <= current_high_bid:
            return await interaction.response.send_message(f"❌ Bid must be > {current_high_bid}.", ephemeral=True)

        # Refund previous bidder
        previous_bidder_info = self.auction_view.highest_bidders.get(self.player_uuid)
        if previous_bidder_info:
            prev_user_id, prev_bid = previous_bidder_info
            await self.bot.db.update_user_coins(prev_user_id, prev_bid)
            prev_user = self.bot.get_user(prev_user_id)
            if prev_user:
                try:
                    await prev_user.send(f"⚠️ You were outbid on **{self.player_name}**! {prev_bid} coins refunded.")
                except discord.HTTPException:
                    pass

        # Deduct coins
        await self.bot.db.update_user_coins(user_id, -bid_amount)
        
        # Update state
        self.auction_view.bids[self.player_uuid] = bid_amount
        self.auction_view.highest_bidders[self.player_uuid] = (user_id, bid_amount)

        # Update button label
        for item in self.auction_view.children:
            if isinstance(item, discord.ui.Button) and item.custom_id == f"bid_{self.player_uuid}":
                item.label = f"Bid on {self.player_name} (Current: {bid_amount})"
                break

        await interaction.response.edit_message(view=self.auction_view)
        await interaction.followup.send(f"✅ Successfully bid {bid_amount} on {self.player_name}!", ephemeral=True)

class AuctionView(discord.ui.View):
    def __init__(self, bot, players):
        super().__init__(timeout=300)
        self.bot = bot
        self.players = players
        self.bids = {p['uuid']: 0 for p in players}
        self.highest_bidders = {}
        self.message = None

        for p in players:
            btn = discord.ui.Button(
                label=f"Bid on {p['current_name']}",
                style=discord.ButtonStyle.primary,
                custom_id=f"bid_{p['uuid']}"
            )
            btn.callback = self.make_callback(p['uuid'], p['current_name'])
            self.add_item(btn)

    def make_callback(self, player_uuid, player_name):
        async def callback(interaction: discord.Interaction):
            modal = BidModal(self.bot, player_uuid, player_name, self)
            await interaction.response.send_modal(modal)
        return callback

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        
        for player_uuid, (user_id, bid_amount) in self.highest_bidders.items():
            await self.bot.db.add_card_to_user(user_id, player_uuid)
            
        if self.message:
            try:
                await self.message.edit(view=self)
                await self.message.channel.send("🏁 The auction has ended! Winners have received their cards.")
            except discord.HTTPException:
                pass

class Auction(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="drop", description="Trigger a card drop (The Sink)")
    @app_commands.checks.has_permissions(administrator=True)
    async def drop_cards(self, interaction: discord.Interaction):
        if getattr(self.bot, 'db', None) is None:
            return await interaction.response.send_message("Database not connected.", ephemeral=True)

        await interaction.response.defer()

        players = await self.bot.db.get_random_unbanned_players(limit=4)
        if not players:
            return await interaction.followup.send("No eligible players found.")

        embed = discord.Embed(
            title="🃏 Card Drop Auction! (The Sink)",
            description="4 cards have dropped. Click a button below to bid.\\nYou can only hold the highest bid on ONE card at a time!",
            color=discord.Color.purple()
        )
        
        for p in players:
            embed.add_field(name=p['current_name'], value=f"Rating: {p['current_drating']}", inline=False)

        view = AuctionView(self.bot, players)
        msg = await interaction.followup.send(embed=embed, view=view)
        view.message = msg

async def setup(bot):
    await bot.add_cog(Auction(bot))
