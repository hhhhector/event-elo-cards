import discord
from discord import app_commands
from discord.ext import commands, tasks
from src import config

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.faucet_task.start()

    def cog_unload(self):
        self.faucet_task.cancel()

    @tasks.loop(hours=24)
    async def faucet_task(self):
        if getattr(self.bot, 'db', None) is None:
            return
        try:
            await self.bot.db.process_faucet_dividends(roi_divisor=4)
            print("Processed daily dividends!")
        except Exception as e:
            print(f"Error processing dividends: {e}")

    @faucet_task.before_loop
    async def before_faucet_task(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="bank", description="Liquidate a card for immediate cash (drating value)")
    @app_commands.describe(card_id="The ID of the card to sell to the bank")
    async def bank(self, interaction: discord.Interaction, card_id: int):
        user_cards = await self.bot.db.get_user_cards(interaction.user.id)
        target_card = next((c for c in user_cards if c['card_id'] == card_id), None)
        
        if not target_card:
            return await interaction.response.send_message("❌ You do not own a card with that ID!", ephemeral=True)

        sale_price = target_card['current_drating']
        
        success = await self.bot.db.remove_card(card_id, interaction.user.id)
        if success:
            new_balance = await self.bot.db.update_user_coins(interaction.user.id, sale_price)
            await interaction.response.send_message(f"🏦 Sold **{target_card['current_name']}** for {sale_price} coins!\\nNew Balance: {new_balance}")
        else:
            await interaction.response.send_message("❌ Failed to process the transaction.", ephemeral=True)

    @app_commands.command(name="bal", description="Check your coin balance")
    async def balance(self, interaction: discord.Interaction):
        coins = await self.bot.db.get_user_coins(interaction.user.id)
        await interaction.response.send_message(f"💰 You have **{coins}** coins.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Economy(bot))
