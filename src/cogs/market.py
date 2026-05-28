import uuid

import discord
from discord import app_commands
from discord.ext import commands

from src.utils.autocomplete import card_autocomplete, their_card_autocomplete
from src.utils.economy_utils import esc


class Market(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="sell", description="Offer to sell one of your cards to another player for coins")
    @app_commands.describe(user="The player to sell to", card="Your card to sell", price="Coin price")
    @app_commands.autocomplete(card=card_autocomplete)
    async def sell(self, interaction: discord.Interaction, user: discord.Member, card: str, price: int):
        if getattr(self.bot, "db", None) is None:
            return await interaction.response.send_message("Database not connected.", ephemeral=True)

        await interaction.response.defer()

        if user.id == interaction.user.id:
            return await interaction.followup.send("You can't sell to yourself.", ephemeral=True)

        if price < 1:
            return await interaction.followup.send("Price must be at least ⛃ 1.", ephemeral=True)

        try:
            uuid.UUID(card)
        except ValueError:
            return await interaction.followup.send(
                "Invalid card. Use the autocomplete dropdown.", ephemeral=True
            )

        card_data = await self.bot.db.get_card_by_id(card, interaction.user.id)
        if card_data is None:
            return await interaction.followup.send("You don't own that card.", ephemeral=True)

        result = await self.bot.db.find_and_execute_offer(
            seller_id=interaction.user.id,
            buyer_id=user.id,
            card_id=card,
            coin_amount=price,
            matching_offer_type="buy",
        )

        if result == "success":
            await interaction.followup.send(
                f"Sale complete. {user.mention} bought **{esc(card_data['current_name'])}** "
                f"from {interaction.user.mention} for ⛃ {price:,}."
            )
        elif result == "expired":
            await interaction.followup.send("That buy offer has expired.", ephemeral=True)
        elif result == "card_moved":
            await interaction.followup.send("One of the cards is no longer available.", ephemeral=True)
        elif result == "insufficient_funds":
            await interaction.followup.send(
                f"{user.display_name} no longer has enough coins.", ephemeral=True
            )
        elif result == "roster_full":
            await interaction.followup.send(
                f"{user.display_name}'s roster is full.", ephemeral=True
            )
        elif result == "active_bid":
            await interaction.followup.send(
                f"{user.display_name} has an active bid on an ongoing auction and cannot receive cards right now.",
                ephemeral=True,
            )
        elif result == "not_found":
            await self.bot.db.create_offer(
                seller_id=interaction.user.id,
                buyer_id=user.id,
                card_id=card,
                coin_amount=price,
                offer_type="sell",
            )
            await interaction.followup.send(
                f"**Sale Proposed**\n"
                f"{interaction.user.mention} offers **{esc(card_data['current_name'])}** "
                f"to {user.mention} for ⛃ {price:,}.\n"
                f"{user.mention} — confirm with "
                f"`/buy @{interaction.user.display_name} [the card] {price}` within 5 minutes."
            )

    @app_commands.command(name="buy", description="Offer to buy a card from another player for coins")
    @app_commands.describe(user="The player to buy from", card="Their card to buy", price="Coin price")
    @app_commands.autocomplete(card=their_card_autocomplete)
    async def buy(self, interaction: discord.Interaction, user: discord.Member, card: str, price: int):
        if getattr(self.bot, "db", None) is None:
            return await interaction.response.send_message("Database not connected.", ephemeral=True)

        await interaction.response.defer()

        if user.id == interaction.user.id:
            return await interaction.followup.send("You can't buy from yourself.", ephemeral=True)

        if price < 1:
            return await interaction.followup.send("Price must be at least ⛃ 1.", ephemeral=True)

        try:
            uuid.UUID(card)
        except ValueError:
            return await interaction.followup.send(
                "Invalid card. Use the autocomplete dropdown.", ephemeral=True
            )

        card_data = await self.bot.db.get_card_by_id(card, user.id)
        if card_data is None:
            return await interaction.followup.send(
                f"{user.display_name} doesn't own that card.", ephemeral=True
            )

        buyer_coins = await self.bot.db.get_user_coins(interaction.user.id)
        if buyer_coins is None:
            return await interaction.followup.send("You must run /register first.", ephemeral=True)
        if float(buyer_coins) < price:
            return await interaction.followup.send(
                f"You don't have enough coins (balance: ⛃ {int(float(buyer_coins)):,}).", ephemeral=True
            )

        if await self.bot.db.user_has_active_bid(interaction.user.id):
            return await interaction.followup.send(
                "You have an active bid on an ongoing auction. Wait for it to resolve before buying a card.",
                ephemeral=True,
            )

        result = await self.bot.db.find_and_execute_offer(
            seller_id=user.id,
            buyer_id=interaction.user.id,
            card_id=card,
            coin_amount=price,
            matching_offer_type="sell",
        )

        if result == "success":
            await interaction.followup.send(
                f"Sale complete. {interaction.user.mention} bought **{esc(card_data['current_name'])}** "
                f"from {user.mention} for ⛃ {price:,}."
            )
        elif result == "expired":
            await interaction.followup.send("That sell offer has expired.", ephemeral=True)
        elif result == "card_moved":
            await interaction.followup.send("That card is no longer available.", ephemeral=True)
        elif result == "insufficient_funds":
            await interaction.followup.send(
                "You no longer have enough coins.", ephemeral=True
            )
        elif result == "roster_full":
            await interaction.followup.send("Your roster is full.", ephemeral=True)
        elif result == "active_bid":
            await interaction.followup.send(
                "You have an active bid on an ongoing auction. Wait for it to resolve before buying a card.",
                ephemeral=True,
            )
        elif result == "not_found":
            roster_info = await self.bot.db.get_user_roster_info(interaction.user.id)
            if roster_info is None:
                return await interaction.followup.send("You must run /register first.", ephemeral=True)
            card_count = await self.bot.db.get_user_cards(interaction.user.id)
            if len(card_count) >= roster_info["roster_cap"]:
                return await interaction.followup.send("Your roster is full.", ephemeral=True)

            await self.bot.db.create_offer(
                seller_id=user.id,
                buyer_id=interaction.user.id,
                card_id=card,
                coin_amount=price,
                offer_type="buy",
            )
            await interaction.followup.send(
                f"**Buy Offer Proposed**\n"
                f"{interaction.user.mention} wants to buy **{esc(card_data['current_name'])}** "
                f"from {user.mention} for ⛃ {price:,}.\n"
                f"{user.mention} — confirm with "
                f"`/sell @{interaction.user.display_name} [the card] {price}` within 5 minutes."
            )


async def setup(bot):
    await bot.add_cog(Market(bot))
