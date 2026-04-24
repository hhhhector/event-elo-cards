import discord
from discord import app_commands
from discord.ext import commands

from src import config
from src.utils.autocomplete import card_autocomplete, their_card_autocomplete


class Trade(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="trade", description="Propose or confirm a card trade")
    @app_commands.describe(
        user="The user to trade with",
        my_card="Your card to offer",
        their_card="Their card you want",
    )
    @app_commands.autocomplete(
        my_card=card_autocomplete, their_card=their_card_autocomplete
    )
    async def trade(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        my_card: str,
        their_card: str,
    ):
        await interaction.response.defer()

        if (
            config.TRADE_BETA_USERS is not None
            and interaction.user.id not in config.TRADE_BETA_USERS
        ):
            return await interaction.followup.send(
                "Trading is not yet available.", ephemeral=True
            )

        if user.id == interaction.user.id:
            return await interaction.followup.send(
                "You can't trade with yourself.", ephemeral=True
            )

        if my_card == their_card:
            return await interaction.followup.send(
                "You can't trade a card for itself.", ephemeral=True
            )

        my_card_data = await self.bot.db.get_card_by_id(my_card, interaction.user.id)
        if my_card_data is None:
            return await interaction.followup.send(
                "You don't own that card.", ephemeral=True
            )

        their_card_data = await self.bot.db.get_card_by_id(their_card, user.id)
        if their_card_data is None:
            return await interaction.followup.send(
                f"{user.display_name} doesn't own that card.", ephemeral=True
            )

        # Try to match and execute a pending trade in the other direction.
        # If B runs /trade @A @cardB @cardA, we look for A's earlier proposal.
        result = await self.bot.db.find_and_execute_trade(
            proposer_id=user.id,  # the other user proposed
            receiver_id=interaction.user.id,
            proposer_card_id=their_card,  # what they offered = their_card from our perspective
            receiver_card_id=my_card,  # what they wanted = my_card from our perspective
        )

        if result == "success":
            await interaction.followup.send(
                f"Trade complete. "
                f"{user.mention}'s **{their_card_data['current_name']}** ↔ "
                f"{interaction.user.mention}'s **{my_card_data['current_name']}**"
            )

        elif result == "expired":
            await interaction.followup.send(
                "That trade offer has expired.", ephemeral=True
            )

        elif result == "card_moved":
            await interaction.followup.send(
                "One of the cards is no longer available.", ephemeral=True
            )

        elif result == "not_found":
            # No matching trade from the other side — create a new proposal.
            await self.bot.db.create_trade(
                proposer_id=interaction.user.id,
                receiver_id=user.id,
                proposer_card_id=my_card,
                proposer_player_uuid=str(my_card_data["player_uuid"]),
                receiver_card_id=their_card,
                receiver_player_uuid=str(their_card_data["player_uuid"]),
            )
            await interaction.followup.send(
                f"**Trade Proposed**\n"
                f"{interaction.user.mention} offers **{my_card_data['current_name']}** "
                f"for {user.mention}'s **{their_card_data['current_name']}**\n"
                f"{user.mention} — confirm with "
                f"`/trade @{interaction.user.display_name} [your card] [their card]` within 5 minutes."
            )


async def setup(bot):
    await bot.add_cog(Trade(bot))
