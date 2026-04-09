from discord import app_commands, Interaction


async def card_autocomplete(interaction: Interaction, current: str) -> list[app_commands.Choice[str]]:
    if getattr(interaction.client, 'db', None) is None:
        return []
    cards = await interaction.client.db.get_user_cards(interaction.user.id)
    return [
        app_commands.Choice(
            name=f"{c['current_name']} (#{c['card_id']})",
            value=str(c['card_id'])
        )
        for c in cards
        if current.lower() in c['current_name'].lower() or current in str(c['card_id'])
    ][:25]
