import os

from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
# For testing and rapid iteration, set DEV_GUILD_ID to sync commands instantly
DEV_GUILD_ID = os.getenv("DEV_GUILD_ID")
DROP_CHANNEL_ID = int(os.getenv("DROP_CHANNEL_ID"))
