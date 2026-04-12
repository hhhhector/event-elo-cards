from datetime import datetime, timezone, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks
from src import config
from src.utils.economy_utils import calculate_bank_value
from src.utils.autocomplete import card_autocomplete

STARTING_BALANCE = 300

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

    @tasks.loop(minutes=1)
    async def faucet_task(self):
        if getattr(self.bot, 'db', None) is None:
            return
        state = await self.bot.db.get_system_state()
        if not state:
            return

        now = datetime.now(timezone.utc)
        next_ts = state["next_dividend_timestamp"]

        if next_ts is None:
            next_time = now + timedelta(hours=24)
            await self.bot.db.set_next_dividend_timestamp(next_time)
            print(f"💰 No dividend timestamp set. Scheduled for {next_time.strftime('%Y-%m-%d %H:%M UTC')}.")
            return

        next_ts_utc = next_ts.replace(tzinfo=timezone.utc)

        if next_ts_utc < now - timedelta(minutes=1):
            next_time = now + timedelta(hours=24)
            await self.bot.db.set_next_dividend_timestamp(next_time)
            print(f"💰 Stale dividend timestamp detected. Rescheduled for {next_time.strftime('%Y-%m-%d %H:%M UTC')}.")
            return

        if next_ts_utc <= now:
            try:
                claimed = await self.bot.db.claim_dividend_payout(next_ts, now + timedelta(hours=24))
                if not claimed:
                    print("💰 Dividend payout already claimed by another instance. Skipping.")
                    return
                await self.bot.db.process_faucet_dividends()
                print("✅ Processed daily dividends!")
            except Exception as e:
                print(f"❌ Error processing dividends: {e}")

    @faucet_task.before_loop
    async def before_faucet_task(self):
        await self.bot.wait_until_ready()
        print("✅ Faucet task started.")

    @app_commands.command(name="bank", description="Sell a card directly to the bank for instant coins")
    @app_commands.describe(card_id="The card to sell")
    @app_commands.autocomplete(card_id=card_autocomplete)
    async def bank(self, interaction: discord.Interaction, card_id: str):
        card = await self.bot.db.get_card_by_id(card_id, interaction.user.id)
        if card is None:
            return await interaction.response.send_message("You do not own a card with that ID.", ephemeral=True)

        sale_price = calculate_bank_value(float(card['current_drating']))
        new_balance = await self.bot.db.sell_card_to_bank(card_id, interaction.user.id, sale_price)

        if new_balance is None:
            return await interaction.response.send_message("Failed to process transaction.", ephemeral=True)

        await interaction.response.send_message(
            f"Sold **{card['current_name']}** for ⛃ {sale_price:,}.\nNew balance: ⛃ {int(float(new_balance)):,}"
        )

    @app_commands.command(name="bal", description="Check your coin balance")
    async def balance(self, interaction: discord.Interaction):
        coins = await self.bot.db.get_user_coins(interaction.user.id)
        if coins is None:
            return await interaction.response.send_message("You must run /register first.", ephemeral=True)
        await interaction.response.send_message(f"Balance: ⛃ **{int(float(coins)):,}**", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Economy(bot))
