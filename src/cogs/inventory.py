import discord
from discord import app_commands
from discord.ext import commands
from src.utils.card_generator import generate_card_image

class Inventory(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="inv", description="List your owned cards")
    async def inventory(self, interaction: discord.Interaction):
        if getattr(self.bot, 'db', None) is None:
            return await interaction.response.send_message("Database not connected.", ephemeral=True)

        cards = await self.bot.db.get_user_cards(interaction.user.id)
        if not cards:
            return await interaction.response.send_message("❌ You have no cards!", ephemeral=True)

        description = ""
        for c in cards:
            description += f"`[{c['card_id']}]` **{c['current_name']}** (Rating: {c['current_drating']})\\n"

        embed = discord.Embed(
            title=f"🎒 {interaction.user.name}'s Inventory",
            description=description,
            color=discord.Color.blue()
        )
        embed.set_footer(text="Use /view [id] to see card details")
        
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="view", description="View a specific card's image and details")
    @app_commands.describe(card_id="The ID of the card you want to see")
    async def view_card(self, interaction: discord.Interaction, card_id: int):
        if getattr(self.bot, 'db', None) is None:
            return await interaction.response.send_message("Database not connected.", ephemeral=True)

        await interaction.response.defer()
        
        cards = await self.bot.db.get_user_cards(interaction.user.id)
        target_card = next((c for c in cards if c['card_id'] == card_id), None)
        
        if not target_card:
            return await interaction.followup.send(f"❌ You don't own a card with ID `{card_id}`!", ephemeral=True)

        image_buffer = await generate_card_image(
            player_name=target_card['current_name'],
            drating=target_card['current_drating'],
            uuid=target_card['player_uuid']
        )
        
        file = discord.File(fp=image_buffer, filename="card.png")
        
        embed = discord.Embed(
            title=f"🎴 {target_card['current_name']}",
            description=f"**Rating:** {target_card['current_drating']}\\n**Card ID:** {target_card['card_id']}",
            color=discord.Color.gold()
        )
        embed.set_image(url="attachment://card.png")
        
        await interaction.followup.send(embed=embed, file=file)

async def setup(bot):
    await bot.add_cog(Inventory(bot))
