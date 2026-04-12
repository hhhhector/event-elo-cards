from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from src import config


def fmt(n) -> str:
    return f"{int(n):,}"


def build_embeds(leaderboard_data, economy_stats, last_updated: str):
    coins_rows, portfolio_rows, combined_rows = leaderboard_data

    def leaderboard_field(rows, value_key):
        lines = []
        for i, row in enumerate(rows, 1):
            user_id = int(row["discord_id"])
            value = int(row[value_key])
            lines.append(f"`{i}.` <@{user_id}> — ⛃ {value:,}")
        return "\n".join(lines) if lines else "No data yet."

    leaderboard = discord.Embed(
        title="Leaderboard",
        color=discord.Color.gold(),
    )
    leaderboard.add_field(name="Coins", value=leaderboard_field(coins_rows, "coins"), inline=True)
    leaderboard.add_field(name="Portfolio", value=leaderboard_field(portfolio_rows, "portfolio"), inline=True)
    leaderboard.add_field(name="Combined", value=leaderboard_field(combined_rows, "combined"), inline=True)
    leaderboard.set_footer(text=f"Updated {last_updated} UTC")

    s = economy_stats
    rarity_list = (
        f"🟥 : {s['cards_x']}\n"
        f"🟨 : {s['cards_s']}\n"
        f"🟪 : {s['cards_a']}\n"
        f"🟦 : {s['cards_b']}\n"
        f"🟩 : {s['cards_c']}\n"
        f"⬜ : {s['cards_d']}"
    )

    economy = discord.Embed(
        title="Economy",
        color=discord.Color.blurple(),
    )
    economy.add_field(name="Registered Players", value=fmt(s["total_users"]), inline=True)
    economy.add_field(name="Total Cards", value=fmt(s["total_cards"]), inline=True)
    economy.add_field(name="Coins in Circulation", value=f"⛃ {fmt(s['total_coins'])}", inline=True)
    economy.add_field(name="Daily Yield (all cards)", value=f"⛃ {fmt(s['total_daily_yield'])}/day", inline=True)
    economy.add_field(name="Cards", value=rarity_list, inline=False)
    economy.set_footer(text=f"Updated {last_updated} UTC")

    return leaderboard, economy


class Stats(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.leaderboard_messages: list[discord.Message] = []
        self.stats_loop.start()

    def cog_unload(self):
        self.stats_loop.cancel()

    async def _fetch_data(self):
        coins = await self.bot.db.get_leaderboard_coins()
        portfolio = await self.bot.db.get_leaderboard_portfolio()
        combined = await self.bot.db.get_leaderboard_combined()
        economy = await self.bot.db.get_economy_stats()
        return (coins, portfolio, combined), economy

    async def _update_messages(self):
        leaderboard_data, economy_stats = await self._fetch_data()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        leaderboard_embed, economy_embed = build_embeds(leaderboard_data, economy_stats, now)

        if self.leaderboard_messages:
            try:
                await self.leaderboard_messages[0].edit(embed=leaderboard_embed)
                await self.leaderboard_messages[1].edit(embed=economy_embed)
                print("📊 Stats messages updated.")
                return
            except discord.HTTPException as e:
                print(f"⚠️ Failed to edit stats messages: {e}. Will repost.")
                self.leaderboard_messages = []

        # Post fresh messages and store IDs
        channel = self.bot.get_channel(config.STATS_CHANNEL_ID)
        if not channel:
            print(f"❌ Stats channel {config.STATS_CHANNEL_ID} not found.")
            return

        msg1 = await channel.send(embed=leaderboard_embed)
        msg2 = await channel.send(embed=economy_embed)
        self.leaderboard_messages = [msg1, msg2]

        # Persist the first message ID so we can recover it on restart
        await self.bot.db.set_stats_message_id(msg1.id)
        print(f"📊 Stats messages posted (IDs: {msg1.id}, {msg2.id}).")

    @tasks.loop(minutes=10)
    async def stats_loop(self):
        if getattr(self.bot, "db", None) is None:
            return
        try:
            await self._update_messages()
        except Exception as e:
            print(f"❌ Stats loop error: {e}")

    @stats_loop.before_loop
    async def before_stats_loop(self):
        await self.bot.wait_until_ready()

        # Try to recover existing messages on restart
        channel = self.bot.get_channel(config.STATS_CHANNEL_ID)
        if not channel:
            print(f"❌ Stats channel {config.STATS_CHANNEL_ID} not found on startup.")
            return

        msg_id = await self.bot.db.get_stats_message_id()
        if msg_id:
            try:
                msg1 = await channel.fetch_message(msg_id)
                # Economy embed is always the message right after — fetch last 2 messages
                messages = [m async for m in channel.history(limit=5)]
                msg2 = next((m for m in messages if m.id != msg_id and m.author == self.bot.user), None)
                if msg2:
                    self.leaderboard_messages = [msg1, msg2]
                    print(f"📊 Recovered stats messages on startup.")
                else:
                    self.leaderboard_messages = [msg1]
            except discord.NotFound:
                print("📊 Stored stats message not found — will repost.")

        print("✅ Stats loop started.")


async def setup(bot):
    await bot.add_cog(Stats(bot))
