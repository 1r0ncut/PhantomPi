import discord
from discord import app_commands
from config import GUILD_ID
import aiohttp

def setup(bot):
    @bot.tree.command(name="status", description="Get implant system status", guild=discord.Object(id=GUILD_ID))
    @app_commands.describe(ip="Target implant IP address")
    async def status(interaction: discord.Interaction, ip: str):
        await interaction.response.defer(thinking=True)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"https://{ip}:8443/status", ssl=False, timeout=10) as resp:
                    data = await resp.json()

                    output = (
                        f"📡 Implant System Status ({ip})\n"
                        f"\n🖧 Interfaces\n{data['interfaces']}"
                        f"\n\n🛣️ Routes\n{data['routes']}"
                        f"\n\n⏱ Uptime\n{data['uptime']}"
                        f"\n\n📡 Listening Ports\n{data['ports']}"
                        f"\n\n🧩 Services\n{data['services']}"
                    )

                    await interaction.followup.send(content=f"```yaml\n{output[:1900]}```")

        except Exception as e:
            await interaction.followup.send(f"❌ Error retrieving status: {str(e)}")
