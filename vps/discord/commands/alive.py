import discord
from discord import app_commands
import aiohttp
from config import GUILD_ID

def setup(bot):
    @bot.tree.command(name="alive", description="Check if implant is up", guild=discord.Object(id=GUILD_ID))
    @app_commands.describe(ip="Target implant IP address")
    async def alive(interaction: discord.Interaction, ip:str):
        await interaction.response.defer(thinking=True)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://{ip}:8443/alive", ssl=False, timeout=5) as resp:
                    if resp.status == 200:
                        await interaction.followup.send(f"✅ Implant at {ip} is alive")
                    else:
                        await interaction.followup.send(f"❌ Implant at {ip} is dead")
        except Exception as e:
            await interaction.followup.send(f"❌ Implant at {ip} is dead")
