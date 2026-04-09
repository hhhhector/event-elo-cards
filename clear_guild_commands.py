"""
One-time script to wipe stale guild-specific slash commands.
Run with: uv run clear_guild_commands.py <guild_id>
"""
import asyncio
import sys
import discord
from src import config


async def main(guild_id: int):
    client = discord.Client(intents=discord.Intents.none())
    await client.login(config.DISCORD_TOKEN)
    result = await client.http.bulk_upsert_guild_commands(client.application_id, guild_id, [])
    print(f"Wiped guild commands for guild {guild_id}. Response: {result}")
    await client.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: uv run clear_guild_commands.py <guild_id>")
        sys.exit(1)
    asyncio.run(main(int(sys.argv[1])))
