import discord
from discord.ext import commands
import logging
from src import config
from src.database import Database

logging.basicConfig(level=logging.INFO)

class TCG_Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.db: Database = None

    async def setup_hook(self):
        logging.info("Connecting to database...")
        db_url = config.DATABASE_URL or "postgresql://postgres:postgres@localhost:5432/postgres"
        try:
            self.db = await Database.create(db_url)
            logging.info("Connected to PostgreSQL successfully.")
        except Exception as e:
            logging.error(f"Failed to connect to database: {e}")

        # Load Cogs
        cogs = [
            "src.cogs.economy",
            "src.cogs.auction",
            "src.cogs.inventory",
            "src.cogs.stats",
            "src.cogs.trade",
            "src.cogs.wishlist",
        ]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                logging.info(f"Loaded {cog}")
            except Exception as e:
                logging.error(f"Failed to load {cog}: {e}")

        # Sync commands
        if config.DEV_GUILD_ID:
            guild = discord.Object(id=int(config.DEV_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logging.info(f"Synced commands to guild {config.DEV_GUILD_ID}")
            logging.info(f"application_id at setup_hook: {self.application_id}")
        else:
            await self.tree.sync()
            logging.info("Synced commands globally")

    async def close(self):
        if self.db:
            await self.db.close()
        await super().close()

def main():
    if not config.DISCORD_TOKEN:
        logging.error("No DISCORD_TOKEN found in environment variables.")
        return

    bot = TCG_Bot()
    bot.run(config.DISCORD_TOKEN)

if __name__ == "__main__":
    main()
