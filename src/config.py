import os

from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
# For testing and rapid iteration, set DEV_GUILD_ID to sync commands instantly
DEV_GUILD_ID = os.getenv("DEV_GUILD_ID")
DROP_CHANNEL_ID = int(os.getenv("DROP_CHANNEL_ID"))
STATS_CHANNEL_ID = int(os.getenv("STATS_CHANNEL_ID"))
AUCTION_PING_ROLE_ID = int(os.getenv("AUCTION_PING_ROLE_ID"))

# Temporary beta whitelist for /trade. Set to None to open to everyone.
TRADE_BETA_USERS: set[int] | None = {173501667109502978, 430041165816004618}
