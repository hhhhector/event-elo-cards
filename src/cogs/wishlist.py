import uuid

import discord
from discord import app_commands
from discord.ext import commands

from src.utils.autocomplete import player_autocomplete, wishlist_autocomplete
from src.utils.economy_utils import get_rarity

RARITY_EMOJI = {
    "X": "🟥", "S": "🟨", "A": "🟪", "B": "🟦", "C": "🟩", "D": "⬜",
}


class Wishlist(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    wishlist_group = app_commands.Group(name="wishlist", description="Manage your wishlist")

    @wishlist_group.command(name="view", description="View your wishlist")
    async def wishlist_view(self, interaction: discord.Interaction):
        if getattr(self.bot, "db", None) is None:
            return await interaction.response.send_message("Database not connected.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        entries = await self.bot.db.get_wishlist(interaction.user.id)
        if not entries:
            return await interaction.followup.send("Your wishlist is empty.", ephemeral=True)

        lines = []
        for e in entries:
            emoji = RARITY_EMOJI[get_rarity(e["current_rank"])]
            rating = int(float(e["current_drating"]))
            lines.append(f"{emoji} **{e['current_name']}** `{rating}`")

        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s Wishlist",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"{len(entries)} players")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @wishlist_group.command(name="add", description="Add a player to your wishlist")
    @app_commands.describe(player_id="Player to add")
    @app_commands.autocomplete(player_id=player_autocomplete)
    async def wishlist_add(self, interaction: discord.Interaction, player_id: str):
        if getattr(self.bot, "db", None) is None:
            return await interaction.response.send_message("Database not connected.", ephemeral=True)

        try:
            uuid.UUID(player_id)
        except ValueError:
            return await interaction.response.send_message(
                "Invalid player. Use the autocomplete dropdown.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        added = await self.bot.db.add_to_wishlist(interaction.user.id, player_id)
        if added:
            player = await self.bot.db.get_player_extended_stats(player_id)
            name = player["current_name"] if player else player_id
            await interaction.followup.send(f"Added **{name}** to your wishlist.", ephemeral=True)
        else:
            await interaction.followup.send("That player is already on your wishlist.", ephemeral=True)

    @wishlist_group.command(name="remove", description="Remove a player from your wishlist")
    @app_commands.describe(player_id="Player to remove")
    @app_commands.autocomplete(player_id=wishlist_autocomplete)
    async def wishlist_remove(self, interaction: discord.Interaction, player_id: str):
        if getattr(self.bot, "db", None) is None:
            return await interaction.response.send_message("Database not connected.", ephemeral=True)

        try:
            uuid.UUID(player_id)
        except ValueError:
            return await interaction.response.send_message(
                "Invalid player. Use the autocomplete dropdown.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        removed = await self.bot.db.remove_from_wishlist(interaction.user.id, player_id)
        if removed:
            await interaction.followup.send("Removed from your wishlist.", ephemeral=True)
        else:
            await interaction.followup.send("That player wasn't on your wishlist.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Wishlist(bot))
