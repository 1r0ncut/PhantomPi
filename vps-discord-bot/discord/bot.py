import discord
from discord.ext import commands
import aiohttp
import asyncio
import os
import logging
from config import DISCORD_TOKEN, GUILD_ID

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)
session = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/opt/implant/discord/logs/bot.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Dynamically load commands
for filename in os.listdir("commands"):
    if filename.endswith(".py") and filename != "__init__.py":
        mod = __import__(f"commands.{filename[:-3]}", fromlist=["setup"])
        if hasattr(mod, "setup"):
            mod.setup(bot)

@bot.event
async def on_ready():
    print(f"✅ Bot connected as {bot.user}")
    try:
        synced = await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print(f"Synced {len(synced)} commands to guild {GUILD_ID}")
    except Exception as e:
        print(f"Command sync failed: {e}")

async def main():
    global session
    session = aiohttp.ClientSession()
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
