from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from src import config
from src.utils.autocomplete import card_autocomplete
from src.utils.economy_utils import (
    BASE_ROSTER_CAP,
    MAX_ROSTER_CAP,
    ROSTER_UPGRADE_PRICES,
    calculate_bank_value,
    esc,
    sell_hold_remaining,
)

STARTING_BALANCE = 1000


class UpgradeConfirmView(discord.ui.View):
    def __init__(self, bot, discord_id: int, current_cap: int, price: int):
        super().__init__(timeout=30)
        self.bot = bot
        self.discord_id = discord_id
        self.current_cap = current_cap
        self.price = price
        self.message: discord.Message | None = None

    @discord.ui.button(label="Upgrade", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.discord_id:
            return await interaction.response.send_message("This isn't your upgrade.", ephemeral=True)
        for item in self.children:
            item.disabled = True
        result = await self.bot.db.upgrade_roster_cap(self.discord_id)
        if result == "not_registered":
            await interaction.response.edit_message(content="You're not registered.", embed=None, view=self)
        elif result == "already_maxed":
            await interaction.response.edit_message(
                content=f"You're already at max capacity ({MAX_ROSTER_CAP} slots).", embed=None, view=self
            )
        elif result == "insufficient_funds":
            await interaction.response.edit_message(
                content=f"Insufficient funds. You need ⛃ {self.price:,}.", embed=None, view=self
            )
        else:
            _, new_cap, new_balance = result
            await interaction.response.edit_message(
                content=f"Done. Capacity upgraded to **{new_cap} slots**. New balance: ⛃ {new_balance:,}",
                embed=None,
                view=self,
            )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="Cancelled.", embed=None, view=self)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(content="Timed out.", embed=None, view=self)
            except discord.HTTPException:
                pass


def next_noon_utc(now: datetime) -> datetime:
    today_noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
    if now >= today_noon:
        return today_noon + timedelta(days=1)
    return today_noon


class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.faucet_task.start()

    def cog_unload(self):
        self.faucet_task.cancel()

    @app_commands.command(
        name="register", description="Join the game and receive starting coins"
    )
    async def register(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        success = await self.bot.db.register_user(interaction.user.id, STARTING_BALANCE)
        if success:
            await interaction.followup.send(
                f"Welcome. You have received {STARTING_BALANCE:,} starting coins.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "You are already registered.", ephemeral=True
            )

    @tasks.loop(minutes=1)
    async def faucet_task(self):
        if getattr(self.bot, "db", None) is None:
            return
        state = await self.bot.db.get_system_state()
        if not state:
            return

        now = datetime.now(timezone.utc)
        next_ts = state["next_dividend_timestamp"]

        if next_ts is None:
            next_time = next_noon_utc(now)
            await self.bot.db.set_next_dividend_timestamp(next_time)
            print(
                f"💰 No dividend timestamp set. Scheduled for {next_time.strftime('%Y-%m-%d %H:%M UTC')}."
            )
            return

        next_ts_utc = next_ts.replace(tzinfo=timezone.utc)

        if next_ts_utc < now - timedelta(minutes=1):
            next_time = next_noon_utc(now)
            await self.bot.db.set_next_dividend_timestamp(next_time)
            print(
                f"💰 Stale dividend timestamp detected. Rescheduled for {next_time.strftime('%Y-%m-%d %H:%M UTC')}."
            )
            return

        if next_ts_utc <= now:
            try:
                next_time = next_noon_utc(now)
                claimed = await self.bot.db.claim_dividend_payout(next_ts, next_time)
                if not claimed:
                    print(
                        "💰 Dividend payout already claimed by another instance. Skipping."
                    )
                    return
                await self.bot.db.process_faucet_dividends()
                print(
                    f"✅ Processed daily dividends! Next payout: {next_time.strftime('%Y-%m-%d %H:%M UTC')}."
                )
            except Exception as e:
                print(f"❌ Error processing dividends: {e}")

    @faucet_task.before_loop
    async def before_faucet_task(self):
        await self.bot.wait_until_ready()
        print("✅ Faucet task started.")

    @app_commands.command(
        name="bank", description="Sell a card directly to the bank for instant coins"
    )
    @app_commands.describe(card_id="The card to sell")
    @app_commands.autocomplete(card_id=card_autocomplete)
    async def bank(self, interaction: discord.Interaction, card_id: str):
        await interaction.response.defer()
        card = await self.bot.db.get_card_by_id(card_id, interaction.user.id)
        if card is None:
            return await interaction.followup.send(
                "You do not own a card with that ID.", ephemeral=True
            )

        hold_remaining = sell_hold_remaining(card["acquired_at"])
        if hold_remaining:
            return await interaction.followup.send(
                f"Cards must be held for 8 hours before selling. Available in {hold_remaining}.",
                ephemeral=True,
            )

        sale_price = calculate_bank_value(float(card["current_drating"]))
        new_balance = await self.bot.db.sell_card_to_bank(
            card_id, interaction.user.id, sale_price
        )

        if new_balance is None:
            return await interaction.followup.send(
                "Failed to process transaction.", ephemeral=True
            )

        try:
            rank_raw = card.get("current_rank")
            rank = int(rank_raw) if rank_raw is not None else None
            acquired_at = card["acquired_at"].replace(tzinfo=timezone.utc)
            held_seconds = int(
                (datetime.now(timezone.utc) - acquired_at).total_seconds()
            )
            await self.bot.db.log_sale(
                interaction.user.id,
                card["player_uuid"],
                float(card["current_drating"]),
                rank,
                sale_price,
                held_seconds,
            )
        except Exception as e:
            print(f"⚠️ Failed to log sale: {e}")

        await interaction.followup.send(
            f"Sold **{esc(card['current_name'])}** for ⛃ {sale_price:,}.\nNew balance: ⛃ {int(float(new_balance)):,}"
        )

    @app_commands.command(name="upgradeinventory", description="Purchase an additional card slot")
    async def upgrade_inventory(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        roster_info = await self.bot.db.get_user_roster_info(interaction.user.id)
        if roster_info is None:
            return await interaction.followup.send("You must run /register first.", ephemeral=True)

        cap = int(roster_info["roster_cap"])
        if cap >= MAX_ROSTER_CAP:
            return await interaction.followup.send(
                f"You're already at max capacity ({MAX_ROSTER_CAP} slots).", ephemeral=True
            )

        price = ROSTER_UPGRADE_PRICES[cap - BASE_ROSTER_CAP]
        balance = int(float(roster_info["coins"]))
        can_afford = balance >= price

        embed = discord.Embed(
            title="Upgrade Inventory?",
            description=(
                f"**Current capacity:** {cap} slots\n"
                f"**New capacity:** {cap + 1} slots\n\n"
                f"**Cost:** ⛃ {price:,}\n"
                f"**Your balance:** ⛃ {balance:,}"
            ),
            color=discord.Color.green() if can_afford else discord.Color.red(),
        )

        view = UpgradeConfirmView(self.bot, interaction.user.id, cap, price)
        msg = await interaction.followup.send(embed=embed, view=view, ephemeral=True, wait=True)
        view.message = msg

    @app_commands.command(name="bal", description="Check your coin balance")
    async def balance(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        coins = await self.bot.db.get_user_coins(interaction.user.id)
        if coins is None:
            return await interaction.followup.send(
                "You must run /register first.", ephemeral=True
            )
        await interaction.followup.send(
            f"Balance: ⛃ **{int(float(coins)):,}**", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Economy(bot))
