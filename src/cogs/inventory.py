import discord
from discord import app_commands
from discord.ext import commands

from src.utils.autocomplete import card_autocomplete
from src.utils.card_generator import generate_card_image
from src.utils.economy_utils import (
    calculate_bank_value,
    calculate_yield_value,
    get_rarity,
)

RARITY_EMOJI = {
    "X": "🟥",
    "S": "🟨",
    "A": "🟪",
    "B": "🟦",
    "C": "🟩",
    "D": "⬜",
}

RARITY_COLOR = {
    "X": 0xEF4444,
    "S": 0xF59E0B,
    "A": 0xA855F7,
    "B": 0x0EA5E9,
    "C": 0x22C55E,
    "D": 0x64748B,
}


class Inventory(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="inv", description="List your owned cards")
    async def inventory(self, interaction: discord.Interaction):
        if getattr(self.bot, "db", None) is None:
            return await interaction.response.send_message(
                "Database not connected.", ephemeral=True
            )

        roster_info = await self.bot.db.get_user_roster_info(interaction.user.id)
        if roster_info is None:
            return await interaction.response.send_message(
                "You must run /register first.", ephemeral=True
            )

        cards = await self.bot.db.get_user_cards(interaction.user.id)
        if not cards:
            return await interaction.response.send_message(
                "You have no cards.", ephemeral=True
            )

        lines = []
        for c in cards:
            rating = int(float(c["current_drating"]))
            rarity = get_rarity(c["current_rank"])
            emoji = RARITY_EMOJI[rarity]
            bv = calculate_bank_value(float(c["current_drating"]))
            yield_val = calculate_yield_value(bv)
            lines.append(
                f"{emoji} **{c['current_name']}** `{rating}` · ⛃ {bv:,} · ⛃ {yield_val:,}/day"
            )

        description = "\n".join(lines)

        balance = int(float(roster_info["coins"]))
        roster_cap = roster_info["roster_cap"]

        embed = discord.Embed(
            title=f"{interaction.user.name}'s Inventory",
            description=description,
            color=discord.Color.blue(),
        )
        embed.set_footer(text=f"{len(cards)}/{roster_cap} cards · ⛃ {balance:,}")


        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="view", description="View a specific card's image and details"
    )
    @app_commands.describe(card_id="The card you want to view")
    @app_commands.autocomplete(card_id=card_autocomplete)
    async def view_card(self, interaction: discord.Interaction, card_id: str):
        if getattr(self.bot, "db", None) is None:
            return await interaction.response.send_message(
                "Database not connected.", ephemeral=True
            )

        coins = await self.bot.db.get_user_coins(interaction.user.id)
        if coins is None:
            return await interaction.response.send_message(
                "You must run /register first.", ephemeral=True
            )

        await interaction.response.defer()

        target_card = await self.bot.db.get_card_by_id(card_id, interaction.user.id)
        if not target_card:
            return await interaction.followup.send(
                f"You don't own a card with ID `{card_id}`.", ephemeral=True
            )

        # Fetch detailed stats (Rank, Peak, etc.)
        extended_stats = await self.bot.db.get_player_extended_stats(
            target_card["player_uuid"]
        )

        image_buffer = await generate_card_image(
            dict(extended_stats) if extended_stats else dict(target_card)
        )

        file = discord.File(fp=image_buffer, filename="card.png")

        rating = int(float(target_card["current_drating"]))
        rank = extended_stats["current_rank"] if extended_stats else None
        rarity = get_rarity(rank)
        color = discord.Color(RARITY_COLOR[rarity])
        bv = calculate_bank_value(float(target_card["current_drating"]))
        yield_val = calculate_yield_value(bv)
        embed = discord.Embed(
            title=f"{target_card['current_name']}",
            description=(
                f"**Rating:** {rating}\n"
                f"**Bank Value:** ⛃ {bv:,}\n"
                f"**Daily Yield:** ⛃ {yield_val:,}\n"
                f"**Card ID:** `{str(target_card['card_id'])[:8]}…`\n"
                f"**Owner:** <@{interaction.user.id}>"
            ),
            color=color,
        )
        embed.set_image(url="attachment://card.png")

        await interaction.followup.send(embed=embed, file=file)


async def setup(bot):
    await bot.add_cog(Inventory(bot))
