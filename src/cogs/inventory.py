import asyncio
import uuid

import discord
from discord import app_commands
from discord.ext import commands

from src.utils.autocomplete import all_cards_autocomplete, card_autocomplete
from src.utils.card_generator import generate_card_image
from src.utils.economy_utils import (
    calculate_bank_value,
    calculate_yield_value,
    get_rarity,
    sell_hold_remaining,
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


class ArchiveConfirmView(discord.ui.View):
    def __init__(
        self,
        bot,
        card_id: str,
        owner_id: int,
        card_name: str,
        bank_value: int,
        yield_val: int,
    ):
        super().__init__(timeout=30)
        self.bot = bot
        self.card_id = card_id
        self.owner_id = owner_id
        self.card_name = card_name
        self.bank_value = bank_value
        self.yield_val = yield_val
        self.message: discord.Message | None = None

    @discord.ui.button(label="Archive", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        success = await self.bot.db.archive_card(self.card_id, self.owner_id)
        for item in self.children:
            item.disabled = True
        if success:
            await interaction.response.edit_message(content="Done.", embed=None, view=self)
            await interaction.channel.send(f"<@{self.owner_id}> archived **{self.card_name}**.")
        else:
            await interaction.response.edit_message(
                content="Failed. Card may have already been sold or moved.",
                embed=None,
                view=self,
            )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="Cancelled.", embed=None, view=self
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(content="Timed out.", embed=None, view=self)
            except discord.HTTPException:
                pass


class Inventory(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="inv", description="List owned cards")
    @app_commands.describe(user="Another user's inventory to view (defaults to yours)")
    async def inventory(self, interaction: discord.Interaction, user: discord.Member = None):
        if getattr(self.bot, "db", None) is None:
            return await interaction.response.send_message(
                "Database not connected.", ephemeral=True
            )

        await interaction.response.defer()

        target = user or interaction.user

        roster_info = await self.bot.db.get_user_roster_info(target.id)
        if roster_info is None:
            msg = "You must run /register first." if target == interaction.user else f"{target.display_name} hasn't registered yet."
            return await interaction.followup.send(msg, ephemeral=True)

        cards, archived = await asyncio.gather(
            self.bot.db.get_user_cards(target.id),
            self.bot.db.get_archived_cards(target.id),
        )

        if not cards and not archived:
            msg = "You have no cards." if target == interaction.user else f"{target.display_name} has no cards."
            return await interaction.followup.send(msg, ephemeral=True)

        balance = int(float(roster_info["coins"]))
        roster_cap = roster_info["roster_cap"]

        active_lines = []
        total_yield = 0
        for c in cards:
            rating = int(float(c["current_drating"]))
            rarity = get_rarity(c["current_rank"])
            emoji = RARITY_EMOJI[rarity]
            bv = calculate_bank_value(float(c["current_drating"]))
            yield_val = calculate_yield_value(bv, c["current_rank"])
            total_yield += yield_val
            hold = sell_hold_remaining(c["acquired_at"])
            hold_str = f" · ⧗ {hold}" if hold else ""
            active_lines.append(
                f"{emoji} **{c['current_name']}** `{rating}` · ⛃ {bv:,} · ⛃ {yield_val:,}/day{hold_str}"
            )

        embed = discord.Embed(
            title=f"{target.display_name}'s Inventory",
            description="\n".join(active_lines) if active_lines else "No active cards.",
            color=discord.Color.blue(),
        )
        embed.set_footer(
            text=f"{len(cards)}/{roster_cap} cards · ⛃ {balance:,} · ⛃ {total_yield:,}/day"
        )

        if archived:
            archived_lines = []
            for c in archived:
                rating = int(float(c["current_drating"]))
                rarity = get_rarity(c["current_rank"])
                emoji = RARITY_EMOJI[rarity]
                bv = calculate_bank_value(float(c["current_drating"]))
                archived_lines.append(
                    f"{emoji} **{c['current_name']}** `{rating}` · ⛃ {bv:,}"
                )
            embed.add_field(
                name=f"Archived ({len(archived)})",
                value="\n".join(archived_lines),
                inline=False,
            )

        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="view", description="View a specific card's image and details"
    )
    @app_commands.describe(card_id="The card you want to view")
    @app_commands.autocomplete(card_id=all_cards_autocomplete)
    async def view_card(self, interaction: discord.Interaction, card_id: str):
        if getattr(self.bot, "db", None) is None:
            return await interaction.response.send_message(
                "Database not connected.", ephemeral=True
            )

        try:
            uuid.UUID(card_id)
        except ValueError:
            return await interaction.response.send_message(
                "Invalid card ID. Use the autocomplete dropdown to select a card.",
                ephemeral=True,
            )

        await interaction.response.defer()

        if await self.bot.db.get_user_coins(interaction.user.id) is None:
            return await interaction.followup.send(
                "You must run /register first.", ephemeral=True
            )

        target_card = await self.bot.db.get_card_by_id(card_id, interaction.user.id)
        is_archived = False

        if not target_card:
            target_card = await self.bot.db.get_archived_card_by_id(
                card_id, interaction.user.id
            )
            is_archived = True

        if not target_card:
            return await interaction.followup.send(
                f"You don't own a card with ID `{card_id}`.", ephemeral=True
            )

        extended_stats, card_counts = await asyncio.gather(
            self.bot.db.get_player_extended_stats(target_card["player_uuid"]),
            self.bot.db.get_player_card_counts(target_card["player_uuid"]),
        )
        image_buffer = await generate_card_image(
            dict(extended_stats) if extended_stats else dict(target_card)
        )
        file = discord.File(fp=image_buffer, filename="card.png")

        rating = int(float(target_card["current_drating"]))
        rank = extended_stats["current_rank"] if extended_stats else None
        rarity = get_rarity(rank)
        bv = calculate_bank_value(float(target_card["current_drating"]))

        if is_archived:
            status_str = "Archived"
            color = discord.Color(RARITY_COLOR[rarity])
            yield_str = "⛃ 0"
        else:
            yield_val = calculate_yield_value(bv, rank)
            hold = sell_hold_remaining(target_card["acquired_at"])
            status_str = f"Not Sellable (⧗ {hold})" if hold else "Sellable"
            color = discord.Color(RARITY_COLOR[rarity])
            yield_str = f"⛃ {yield_val:,}"

        active_count = int(card_counts["active"])
        archived_count = int(card_counts["archived"])
        existing_str = f"{active_count}" if not archived_count else f"{active_count} (+{archived_count} archived)"

        embed = discord.Embed(
            title=target_card["current_name"],
            description=(
                f"**Rating:** {rating}\n"
                f"**Bank Value:** ⛃ {bv:,}\n"
                f"**Daily Yield:** {yield_str}\n"
                f"**Status:** {status_str}\n"
                f"**Card ID:** `{str(target_card['card_id'])[:8]}…`\n"
                f"**Owner:** <@{interaction.user.id}>\n"
                f"**Existing:** {existing_str}"
            ),
            color=color,
        )
        embed.set_image(url="attachment://card.png")

        await interaction.followup.send(embed=embed, file=file)

    @app_commands.command(
        name="archive",
        description="Permanently archive a card, eliminating its yield and ability to be sold. Frees up a roster slot.",
    )
    @app_commands.describe(card_id="The card to archive")
    @app_commands.autocomplete(card_id=card_autocomplete)
    async def archive_card(self, interaction: discord.Interaction, card_id: str):
        if getattr(self.bot, "db", None) is None:
            return await interaction.response.send_message(
                "Database not connected.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        roster_info = await self.bot.db.get_user_roster_info(interaction.user.id)
        if roster_info is None:
            return await interaction.followup.send(
                "You must run /register first.", ephemeral=True
            )

        card = await self.bot.db.get_card_by_id(card_id, interaction.user.id)
        if card is None:
            return await interaction.followup.send(
                "You don't own a card with that ID.", ephemeral=True
            )

        bv = calculate_bank_value(float(card["current_drating"]))
        rank = card.get("current_rank")
        yield_val = calculate_yield_value(bv, rank)
        rarity = get_rarity(rank)
        color = discord.Color(RARITY_COLOR[rarity])
        roster_cap = roster_info["roster_cap"]

        embed = discord.Embed(
            title=f"Archive {card['current_name']}?",
            description=(
                "This is **permanent and irreversible**.\n\n"
                f"**Bank Value:** ⛃ {bv:,}\n"
                f"**Daily Yield:** ⛃ {yield_val:,}\n\n"
                f"The card won't count toward your {roster_cap}-card roster cap."
            ),
            color=color,
        )

        view = ArchiveConfirmView(
            self.bot,
            card_id,
            interaction.user.id,
            card["current_name"],
            bv,
            yield_val,
        )
        msg = await interaction.followup.send(
            embed=embed, view=view, ephemeral=True, wait=True
        )
        view.message = msg


async def setup(bot):
    await bot.add_cog(Inventory(bot))
