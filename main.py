import asyncio
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
import database
 
load_dotenv()
 
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
 
bot = commands.Bot(command_prefix='!', intents=intents)
 
COGS = ['tickets', 'events', 'bank', 'members', 'welcome', 'setup']
 
@bot.event
async def on_ready():
    database.init_db()
    print(f'✅  XnoMercy Bot online como {bot.user}')
    try:
        for guild in bot.guilds:
            synced = await bot.tree.sync(guild=guild)
            print(f'✅  {len(synced)} comandos em: {guild.name}')
    except Exception as e:
        print(f'❌  Erro: {e}')
 
async def main():
    async with bot:
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                print(f'✅  Cog: {cog}')
            except Exception as e:
                print(f'❌  Erro em {cog}: {e}')
        await bot.start(os.getenv('TOKEN'))
 
if __name__ == '__main__':
    asyncio.run(main())
 
