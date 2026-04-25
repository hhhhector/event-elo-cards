import asyncio
import io
from collections import defaultdict
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from src import config

try:
    import plotly.graph_objects as go

    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False


WEALTH_ROLES = [
    (0,        1497664499275010081),  # Aficionado
    (1000,     1497664836937580555),  # Amateur
    (2000,     1497664968122826926),  # Grand Amateur
    (4000,     1497665109898559610),  # Collector
    (8000,     1497665383367446589),  # Grand Collector
    (16000,    1497665503983046716),  # Appraiser
    (32000,    1497665607275905274),  # Grand Appraiser
    (64000,    1497665722199965776),  # Gourmand
    (128000,   1497665844426178711),  # Grand Gourmand
    (256000,   1497666043592708226),  # Sommelier
    (512000,   1497666240498368652),  # Grand Sommelier
    (1024000,  1497666395750662304),  # Connoisseur
    (2048000,  1497666562252083281),  # Grand Connoisseur
]
_WEALTH_ROLE_IDS = {role_id for _, role_id in WEALTH_ROLES}


def _target_role_id(combined: float) -> int:
    target = WEALTH_ROLES[0][1]
    for threshold, role_id in WEALTH_ROLES:
        if combined >= threshold:
            target = role_id
    return target


RARITY_COLOR_HEX = {
    "X": "#EF4444",
    "S": "#F59E0B",
    "A": "#A855F7",
    "B": "#0EA5E9",
    "C": "#22C55E",
    "D": "#64748B",
}

RARITY_ORDER = ["X", "S", "A", "B", "C", "D"]


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
    leaderboard.add_field(
        name="Coins", value=leaderboard_field(coins_rows, "coins"), inline=True
    )
    leaderboard.add_field(
        name="Portfolio",
        value=leaderboard_field(portfolio_rows, "portfolio"),
        inline=True,
    )
    leaderboard.add_field(
        name="Combined", value=leaderboard_field(combined_rows, "combined"), inline=True
    )
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
    economy.add_field(
        name="Registered Players", value=fmt(s["total_users"]), inline=True
    )
    economy.add_field(name="Total Cards", value=fmt(s["total_cards"]), inline=True)
    economy.add_field(
        name="Coins in Circulation", value=f"⛃ {fmt(s['total_coins'])}", inline=True
    )
    economy.add_field(
        name="Daily Yield (all cards)",
        value=f"⛃ {fmt(s['total_daily_yield'])}/day",
        inline=True,
    )
    economy.add_field(name="Cards", value=rarity_list, inline=False)
    economy.set_footer(text=f"Updated {last_updated} UTC")

    return leaderboard, economy


def _render_kpi_chart(snapshots, scatter_rows) -> bytes | None:
    if not PLOTLY_AVAILABLE:
        return None

    line_series = defaultdict(lambda: {"x": [], "y": []})
    for row in snapshots:
        avg = row["median_wb_over_bv"]
        if avg is None:
            continue
        line_series[row["rarity"]]["x"].append(row["taken_at"])
        line_series[row["rarity"]]["y"].append(float(avg))

    dot_series = defaultdict(lambda: {"x": [], "y": []})
    for row in scatter_rows:
        dot_series[row["rarity"]]["x"].append(row["closed_at"])
        dot_series[row["rarity"]]["y"].append(float(row["wb_over_bv"]))

    if not line_series and not dot_series:
        return None

    fig = go.Figure()

    # Scatter underneath, trendline on top, both colored by rarity and grouped in legend.
    for rarity in RARITY_ORDER:
        color = RARITY_COLOR_HEX[rarity]
        if rarity in dot_series:
            fig.add_trace(
                go.Scatter(
                    x=dot_series[rarity]["x"],
                    y=dot_series[rarity]["y"],
                    mode="markers",
                    name=rarity,
                    legendgroup=rarity,
                    showlegend=False,
                    marker=dict(color=color, size=9, opacity=0.35),
                    hovertemplate="%{x|%H:%M}<br>WB/BV: %{y:.2f}<extra></extra>",
                )
            )
        if rarity in line_series:
            fig.add_trace(
                go.Scatter(
                    x=line_series[rarity]["x"],
                    y=line_series[rarity]["y"],
                    mode="lines",
                    name=rarity,
                    legendgroup=rarity,
                    line=dict(color=color, width=5),
                    hovertemplate="%{x|%H:%M}<br>mean WB/BV: %{y:.3f}<extra></extra>",
                )
            )

    fig.add_hline(
        y=1.0,
        line=dict(color="rgba(255,255,255,0.3)", width=2, dash="dash"),
    )

    fig.update_layout(
        title=dict(
            text="Winning Bid / Bank Value · 24h scatter + 6h rolling mean, by rarity",
            font=dict(size=28),
        ),
        xaxis=dict(
            title=dict(text="Time (UTC)", font=dict(size=20)), tickfont=dict(size=16)
        ),
        yaxis=dict(
            title=dict(text="WB / BV", font=dict(size=20)), tickfont=dict(size=16)
        ),
        template="plotly_dark",
        width=1800,
        height=1200,
        font=dict(size=16),
        margin=dict(l=120, r=40, t=120, b=100),
        legend=dict(orientation="h", y=-0.15, font=dict(size=18)),
    )
    return fig.to_image(format="png")


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

    async def _build_chart_bytes(self) -> bytes | None:
        try:
            await self.bot.db.insert_kpi_snapshots()
        except Exception as e:
            print(f"⚠️ Failed to insert KPI snapshot: {e}")

        try:
            snapshots = await self.bot.db.get_kpi_snapshots(hours=24)
            scatter_rows = await self.bot.db.get_winning_bid_scatter(hours=24)
        except Exception as e:
            print(f"⚠️ Failed to fetch KPI data: {e}")
            return None

        if not snapshots and not scatter_rows:
            return None

        try:
            return await asyncio.to_thread(_render_kpi_chart, snapshots, scatter_rows)
        except Exception as e:
            print(f"⚠️ Failed to render KPI chart: {e}")
            return None

    async def _update_messages(self):
        leaderboard_data, economy_stats = await self._fetch_data()
        chart_bytes = await self._build_chart_bytes()

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        leaderboard_embed, economy_embed = build_embeds(
            leaderboard_data, economy_stats, now
        )

        if chart_bytes:
            economy_embed.set_image(url="attachment://kpi_chart.png")

        def new_chart_file():
            return (
                discord.File(io.BytesIO(chart_bytes), filename="kpi_chart.png")
                if chart_bytes
                else None
            )

        if self.leaderboard_messages:
            try:
                await self.leaderboard_messages[0].edit(embed=leaderboard_embed)
                chart_file = new_chart_file()
                if chart_file is not None:
                    await self.leaderboard_messages[1].edit(
                        embed=economy_embed, attachments=[chart_file]
                    )
                else:
                    await self.leaderboard_messages[1].edit(
                        embed=economy_embed, attachments=[]
                    )
                print("📊 Stats messages updated.")
                return
            except discord.NotFound:
                print("⚠️ Stats messages were deleted. Will repost.")
                self.leaderboard_messages = []
            except discord.HTTPException as e:
                print(
                    f"⚠️ Failed to edit stats messages (transient): {e}. Skipping this cycle."
                )
                return

        # Post fresh messages and store IDs
        channel = self.bot.get_channel(config.STATS_CHANNEL_ID)
        if not channel:
            print(f"❌ Stats channel {config.STATS_CHANNEL_ID} not found.")
            return

        msg1 = await channel.send(embed=leaderboard_embed)
        chart_file = new_chart_file()
        if chart_file is not None:
            msg2 = await channel.send(embed=economy_embed, file=chart_file)
        else:
            msg2 = await channel.send(embed=economy_embed)
        self.leaderboard_messages = [msg1, msg2]

        # Persist the first message ID so we can recover it on restart
        await self.bot.db.set_stats_message_id(msg1.id)
        print(f"📊 Stats messages posted (IDs: {msg1.id}, {msg2.id}).")

    async def _update_roles(self, guild: discord.Guild):
        rows = await self.bot.db.get_all_users_wealth()
        print(f"🏷️ _update_roles: {len(rows)} users, {len(guild.roles)} roles cached, {len(guild.members)} members cached")
        updates = 0
        for row in rows:
            member = guild.get_member(int(row["discord_id"]))
            if member is None:
                continue
            combined = float(row["combined"])
            target_id = _target_role_id(combined)
            target_role = guild.get_role(target_id)
            if target_role is None:
                continue
            current_wealth_roles = [r for r in member.roles if r.id in _WEALTH_ROLE_IDS]
            already_has_target = any(r.id == target_id for r in current_wealth_roles)
            to_remove = [r for r in current_wealth_roles if r.id != target_id]
            if already_has_target and not to_remove:
                continue
            try:
                if to_remove:
                    await member.remove_roles(*to_remove, reason="Wealth role update")
                if not already_has_target:
                    await member.add_roles(target_role, reason="Wealth role update")
                updates += 1
            except discord.HTTPException as e:
                print(f"⚠️ Role update failed for {member}: {e}")
        if updates:
            print(f"🏷️ Updated wealth roles for {updates} users.")

    @tasks.loop(minutes=10)
    async def stats_loop(self):
        if getattr(self.bot, "db", None) is None:
            return
        try:
            await self._update_messages()
        except Exception as e:
            print(f"❌ Stats loop error: {e}")
        try:
            channel = self.bot.get_channel(config.STATS_CHANNEL_ID)
            if channel:
                await self._update_roles(channel.guild)
        except Exception as e:
            print(f"❌ Roles loop error: {e}")

    @app_commands.command(name="rank", description="See your leaderboard ranks")
    async def rank(self, interaction: discord.Interaction):
        await interaction.response.defer()
        ranks = await self.bot.db.get_user_ranks(interaction.user.id)
        if ranks is None:
            return await interaction.followup.send(
                "You must run /register first.", ephemeral=True
            )

        total = ranks["total_users"]

        def fmt_rank(r) -> str:
            return f"#{r:,} / {total:,}" if r is not None else f"Unranked / {total:,}"

        lines = (
            f"**Coins:** {fmt_rank(ranks['coins_rank'])}\n"
            f"**Portfolio:** {fmt_rank(ranks['portfolio_rank'])}\n"
            f"**Combined:** {fmt_rank(ranks['combined_rank'])}"
        )
        embed = discord.Embed(
            title=f"{interaction.user.display_name}'s Ranks",
            description=lines,
            color=discord.Color.gold(),
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="updaterole", description="Update your wealth role immediately")
    async def updaterole(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        combined = await self.bot.db.get_user_combined_wealth(interaction.user.id)
        if combined is None:
            return await interaction.followup.send("You must /register first.", ephemeral=True)
        guild = interaction.guild
        target_id = _target_role_id(float(combined))
        target_role = guild.get_role(target_id)
        if target_role is None:
            guild_role_ids = [r.id for r in guild.roles]
            print(f"🔍 target_id={target_id}, combined={combined}, guild_role_ids={guild_role_ids}")
            return await interaction.followup.send("Role not found — contact an admin.", ephemeral=True)
        member = interaction.user
        current_wealth_roles = [r for r in member.roles if r.id in _WEALTH_ROLE_IDS]
        already_has_target = any(r.id == target_id for r in current_wealth_roles)
        to_remove = [r for r in current_wealth_roles if r.id != target_id]
        try:
            if to_remove:
                await member.remove_roles(*to_remove, reason="Manual wealth role update")
            if not already_has_target:
                await member.add_roles(target_role, reason="Manual wealth role update")
        except discord.HTTPException as e:
            return await interaction.followup.send(f"Failed to update role: {e}", ephemeral=True)
        await interaction.followup.send(f"Your role is **{target_role.name}**.", ephemeral=True)

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
                msg2 = next(
                    (
                        m
                        for m in messages
                        if m.id != msg_id and m.author == self.bot.user
                    ),
                    None,
                )
                if msg2:
                    self.leaderboard_messages = [msg1, msg2]
                    print(f"📊 Recovered stats messages on startup.")
                else:
                    self.leaderboard_messages = [msg1]
            except discord.NotFound:
                print("📊 Stored stats message not found — will repost.")

        try:
            await self._update_roles(channel.guild)
        except Exception as e:
            print(f"❌ Startup role update error: {e}")

        print("✅ Stats loop started.")


async def setup(bot):
    await bot.add_cog(Stats(bot))
