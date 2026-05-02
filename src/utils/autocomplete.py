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


async def all_cards_autocomplete(interaction: Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Active + archived cards — for /view."""
    if getattr(interaction.client, 'db', None) is None:
        return []
    active = await interaction.client.db.get_user_cards(interaction.user.id)
    archived = await interaction.client.db.get_archived_cards(interaction.user.id)
    choices = []
    for c in active:
        if current.lower() in c['current_name'].lower() or current in str(c['card_id']):
            choices.append(app_commands.Choice(
                name=f"{c['current_name']} (#{c['card_id']})",
                value=str(c['card_id']),
            ))
    for c in archived:
        if current.lower() in c['current_name'].lower() or current in str(c['card_id']):
            choices.append(app_commands.Choice(
                name=f"[Archived] {c['current_name']} (#{c['card_id']})",
                value=str(c['card_id']),
            ))
    return choices[:25]


async def player_autocomplete(interaction: Interaction, current: str) -> list[app_commands.Choice[str]]:
    if getattr(interaction.client, 'db', None) is None:
        return []
    players = await interaction.client.db.search_players_by_name(current)
    return [
        app_commands.Choice(name=c['current_name'], value=str(c['uuid']))
        for c in players
    ]


async def wishlist_autocomplete(interaction: Interaction, current: str) -> list[app_commands.Choice[str]]:
    if getattr(interaction.client, 'db', None) is None:
        return []
    entries = await interaction.client.db.get_wishlist(interaction.user.id)
    return [
        app_commands.Choice(name=c['current_name'], value=str(c['player_uuid']))
        for c in entries
        if current.lower() in c['current_name'].lower()
    ][:25]


async def their_card_autocomplete(interaction: Interaction, current: str) -> list[app_commands.Choice[str]]:
    if getattr(interaction.client, 'db', None) is None:
        return []
    user = getattr(interaction.namespace, 'user', None)
    if user is None:
        return []
    try:
        cards = await interaction.client.db.get_user_cards(user.id)
    except Exception:
        return []
    return [
        app_commands.Choice(
            name=f"{c['current_name']} (#{c['card_id']})",
            value=str(c['card_id'])
        )
        for c in cards
        if current.lower() in c['current_name'].lower() or current in str(c['card_id'])
    ][:25]
