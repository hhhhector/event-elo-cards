import discord
from discord import app_commands
from discord.ext import commands, tasks
from src import config
from src.utils.economy_utils import calculate_bank_value

STARTING_BALANCE = 10000

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.faucet_task.start()

    def cog_unload(self):
        self.faucet_task.cancel()

    @app_commands.command(name="register", description="Join the game and receive starting coins")
    async def register(self, interaction: discord.Interaction):
        success = await self.bot.db.register_user(interaction.user.id, STARTING_BALANCE)
        if success:
            await interaction.response.send_message(
                f"Welcome. You have received {STARTING_BALANCE:,} starting coins.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "You are already registered.",
                ephemeral=True
            )

    @tasks.loop(hours=24)
    async def faucet_task(self):
        if getattr(self.bot, 'db', None) is None:
            return
        try:
            await self.bot.db.process_faucet_dividends()
            print("Processed daily dividends!")
        except Exception as e:
            print(f"Error processing dividends: {e}")

    @faucet_task.before_loop
    async def before_faucet_task(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="bank", description="Liquidate a card for immediate cash (drating value)")
    @app_commands.describe(card_id="The ID of the card to sell to the bank")
    async def bank(self, interaction: discord.Interaction, card_id: str):
        coins = await self.bot.db.get_user_coins(interaction.user.id)
        if coins is None:
            return await interaction.response.send_message("You must run /register first.", ephemeral=True)

        user_cards = await self.bot.db.get_user_cards(interaction.user.id)
        target_card = next((c for c in user_cards if str(c['card_id']) == card_id), None)
        
        if not target_card:
            return await interaction.response.send_message("You do not own a card with that ID.", ephemeral=True)

        rating = float(target_card['current_drating'])
        sale_price = calculate_bank_value(rating)
        
        success = await self.bot.db.remove_card(card_id, interaction.user.id)
        if success:
            new_balance_raw = await self.bot.db.update_user_coins(interaction.user.id, sale_price)
            new_balance = int(float(new_balance_raw)) if new_balance_raw is not None else 0
            await interaction.response.send_message(f"Sold **{target_card['current_name']}** for {sale_price:,}.\nNew balance: {new_balance:,}")
        else:
            await interaction.response.send_message("Failed to process transaction.", ephemeral=True)

    @app_commands.command(name="bal", description="Check your coin balance")
    async def balance(self, interaction: discord.Interaction):
        coins = await self.bot.db.get_user_coins(interaction.user.id)
        if coins is None:
            return await interaction.response.send_message("You must run /register first.", ephemeral=True)
        await interaction.response.send_message(f"Balance: **{coins:,}**", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Economy(bot))
